"""
These regression tests exist specifically because Project B's SECURITY-
AUDIT-REPORT.md found and fixed these exact bugs in the original Worker
code. They are carried over so the same mistakes can't silently reappear
during the Django port. See docs/SECURITY-AUDIT-REPORT.md (Project B)
for the original writeup.
"""
from unittest.mock import patch

from django.test import TestCase

from apps.members.models import County, RegistrationIntent
from apps.payments.models import Payment
from apps.payments.providers import StatusResult
from apps.payments.services import _atomically_mark_paid, handle_callback, transition_status, InvalidTransition


def _make_intent(**overrides):
    """Builds a valid RegistrationIntent for tests. Field names match the
    real registration wizard (surname/other_names, county as an FK, no
    id_number field — see apps.members.models.RegistrationIntent).
    Overrides let individual tests vary phone/email without repeating
    every required field."""
    county, _ = County.objects.get_or_create(name="Nairobi")
    defaults = {
        "surname": "Test", "other_names": "User", "phone_number": "0700000000",
        "email": "t@example.com", "gender": "MALE", "county": county,
    }
    defaults.update(overrides)
    return RegistrationIntent.objects.create(**defaults)


class StateMachineTests(TestCase):
    def test_paid_is_terminal_no_transition_out(self):
        intent = _make_intent()
        payment = Payment.objects.create(purpose="REGISTRATION", amount_kes=500,
                                          phone_number="0700000000", registration_intent=intent,
                                          status="PAID")
        with self.assertRaises(InvalidTransition):
            transition_status(payment, "PROCESSING")


class NoSignatureAssumedTests(TestCase):
    """Regression test for audit finding #1: there is no PayHero signature
    to check. This test exists to make sure nobody re-adds a fabricated
    signature-verification step that would reject every real callback."""

    def test_provider_extract_identifiers_does_not_require_a_signature_field(self):
        from apps.payments.providers import PayHeroProvider

        body = {"response": {"ExternalReference": "abc", "reference": "PH123"}}
        ids = PayHeroProvider().extract_callback_identifiers(body)
        self.assertEqual(ids["provider_reference"], "PH123")


class ReferenceFieldTests(TestCase):
    """Regression test for audit finding #2: status checks must use
    PayHero's `reference`, not `CheckoutRequestID`."""

    @patch("apps.payments.providers.requests.get")
    def test_status_check_uses_reference_not_checkout_request_id(self, mock_get):
        from apps.payments.providers import PayHeroProvider

        mock_get.return_value.ok = True
        mock_get.return_value.json.return_value = {"ResultCode": 0, "Status": "Success"}

        PayHeroProvider().verify_transaction_status("PH-REFERENCE-123")

        called_params = mock_get.call_args.kwargs["params"]
        self.assertEqual(called_params["reference"], "PH-REFERENCE-123")
        self.assertNotIn("CheckoutRequestID", called_params)


class ConcurrentCallbackRaceTests(TestCase):
    """Regression test for audit finding #3: two callbacks racing to
    settle the same PROCESSING payment must not both succeed."""

    def setUp(self):
        self.intent = _make_intent(
            surname="Race", other_names="Test", email="race@example.com", phone_number="0711111111",
        )
        self.payment = Payment.objects.create(
            purpose="REGISTRATION", amount_kes=500, phone_number="0711111111",
            registration_intent=self.intent, status="PROCESSING", provider_reference="PH-RACE",
        )

    def test_second_settlement_attempt_is_a_no_op(self):
        _atomically_mark_paid(self.payment, "MPESA123")
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, "PAID")
        self.assertEqual(self.payment.memberships.count(), 1)

        # Simulate a second, late/duplicate callback trying to settle the
        # same already-PAID payment again.
        _atomically_mark_paid(self.payment, "MPESA123")
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.memberships.count(), 1, "Duplicate settlement must not create a second membership")

    @patch("apps.payments.providers.PayHeroProvider.verify_transaction_status")
    def test_duplicate_callback_via_handle_callback_is_idempotent(self, mock_verify):
        mock_verify.return_value = StatusResult(
            status="PAID", mpesa_receipt="MPESA999", amount=500,
            external_reference=str(self.payment.id), checkout_request_id="ws_CO_1", raw={},
        )
        handle_callback(callback_token=str(self.payment.callback_token), body={})
        handle_callback(callback_token=str(self.payment.callback_token), body={})

        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, "PAID")
        self.assertEqual(self.payment.memberships.count(), 1)


class AmountTamperingTests(TestCase):
    def setUp(self):
        self.intent = _make_intent(
            surname="Amount", other_names="Test", email="amt@example.com", phone_number="0722222222",
        )
        self.payment = Payment.objects.create(
            purpose="REGISTRATION", amount_kes=1000, phone_number="0722222222",
            registration_intent=self.intent, status="PROCESSING", provider_reference="PH-AMT",
        )

    @patch("apps.payments.providers.PayHeroProvider.verify_transaction_status")
    def test_mismatched_amount_is_not_settled(self, mock_verify):
        mock_verify.return_value = StatusResult(
            status="PAID", mpesa_receipt="MPESA1", amount=1,  # attacker paid 1 KES, not 1000
            external_reference=str(self.payment.id), checkout_request_id="ws_CO_2", raw={},
        )
        handle_callback(callback_token=str(self.payment.callback_token), body={})
        self.payment.refresh_from_db()
        self.assertEqual(self.payment.status, "FAILED")
        self.assertEqual(self.payment.memberships.count(), 0)


class ManualPaymentTests(TestCase):
    """Regression tests for the dual payment system's critical business
    rule (spec section 27): a user-submitted transaction code must NEVER
    by itself mark a payment PAID — only an explicit admin verify action
    can, and duplicate transaction codes must be rejected at the
    database level, not just in application code."""

    def setUp(self):
        from django.contrib.auth.models import User

        self.intent = _make_intent(
            surname="Manual", other_names="Payer", email="manual@example.com", phone_number="0733333333",
        )
        self.admin_user = User.objects.create_user(username="finance_admin", password="not-used-in-test")

    def test_submitting_a_manual_payment_never_marks_it_paid(self):
        from datetime import date

        from apps.payments.services import initiate_manual_payment, submit_manual_payment

        payment = initiate_manual_payment(
            purpose="REGISTRATION", amount_kes=200, phone_number="0733333333", registration_intent=self.intent,
        )
        self.assertEqual(payment.status, "PENDING")
        self.assertTrue(payment.application_number.startswith("EGUP-"))

        submit_manual_payment(
            payment=payment, transaction_code="QJI7ABCDEF", phone_number_used="0733333333",
            amount_submitted=200, payment_date=date.today(),
        )
        payment.refresh_from_db()
        self.assertEqual(payment.status, "PENDING_VERIFICATION")
        self.assertEqual(payment.memberships.count(), 0)  # critical: still not a member

    def test_admin_verify_is_the_only_thing_that_marks_it_paid(self):
        from datetime import date

        from apps.payments.services import initiate_manual_payment, submit_manual_payment, verify_manual_payment

        payment = initiate_manual_payment(
            purpose="REGISTRATION", amount_kes=200, phone_number="0733333333", registration_intent=self.intent,
        )
        submission = submit_manual_payment(
            payment=payment, transaction_code="QJI7GHIJKL", phone_number_used="0733333333",
            amount_submitted=200, payment_date=date.today(),
        )
        verify_manual_payment(submission=submission, admin_user=self.admin_user, notes="Matches statement.")

        payment.refresh_from_db()
        self.assertEqual(payment.status, "PAID")
        self.assertEqual(payment.memberships.count(), 1)
        submission.refresh_from_db()
        self.assertEqual(submission.verification_status, "VERIFIED")
        self.assertEqual(submission.verified_by, self.admin_user)

    def test_duplicate_transaction_code_is_rejected_at_the_database_level(self):
        from datetime import date

        from django.core.exceptions import ValidationError

        from apps.payments.services import initiate_manual_payment, submit_manual_payment

        payment1 = initiate_manual_payment(
            purpose="REGISTRATION", amount_kes=200, phone_number="0733333333", registration_intent=self.intent,
        )
        submit_manual_payment(
            payment=payment1, transaction_code="QJI7DUPE001", phone_number_used="0733333333",
            amount_submitted=200, payment_date=date.today(),
        )

        intent2 = _make_intent(surname="Second", other_names="Payer", email="second@example.com", phone_number="0744444444")
        payment2 = initiate_manual_payment(
            purpose="REGISTRATION", amount_kes=200, phone_number="0744444444", registration_intent=intent2,
        )
        with self.assertRaises(ValidationError):
            submit_manual_payment(
                payment=payment2, transaction_code="QJI7DUPE001",  # same code, reused
                phone_number_used="0744444444", amount_submitted=200, payment_date=date.today(),
            )
        payment2.refresh_from_db()
        self.assertEqual(payment2.status, "PENDING")  # unaffected, never advanced

    def test_amount_mismatch_lowers_confidence_but_still_only_pends(self):
        from datetime import date

        from apps.payments.services import initiate_manual_payment, submit_manual_payment

        payment = initiate_manual_payment(
            purpose="REGISTRATION", amount_kes=200, phone_number="0733333333", registration_intent=self.intent,
        )
        submission = submit_manual_payment(
            payment=payment, transaction_code="QJI7LOWAMT1", phone_number_used="0733333333",
            amount_submitted=50, payment_date=date.today(),  # underpaid
        )
        self.assertEqual(submission.confidence, "LOW")
        payment.refresh_from_db()
        self.assertEqual(payment.status, "PENDING_VERIFICATION")  # still just pending, never auto-rejected either

    def test_reject_never_creates_a_member(self):
        from datetime import date

        from apps.payments.services import initiate_manual_payment, reject_manual_payment, submit_manual_payment

        payment = initiate_manual_payment(
            purpose="REGISTRATION", amount_kes=200, phone_number="0733333333", registration_intent=self.intent,
        )
        submission = submit_manual_payment(
            payment=payment, transaction_code="QJI7REJECT1", phone_number_used="0733333333",
            amount_submitted=200, payment_date=date.today(),
        )
        reject_manual_payment(submission=submission, admin_user=self.admin_user, notes="Not found on statement.")
        payment.refresh_from_db()
        self.assertEqual(payment.status, "REJECTED")
        self.assertEqual(payment.memberships.count(), 0)


class ResubmissionAndAccessTokenTests(TestCase):
    """Regression tests for two specific bugs identified in a later
    security review: (1) ManualPaymentSubmission used to be a OneToOne,
    which made it impossible for a rejected applicant to submit a
    corrected payment — fixed by making it a ForeignKey with full
    history; (2) payment status/manual-submit endpoints used to trust a
    payment UUID alone as authorization — fixed with a hashed access
    token issued once at payment creation."""

    def setUp(self):
        from django.contrib.auth.models import User

        self.intent = _make_intent(
            surname="Resubmit", other_names="Test", email="resubmit@example.com", phone_number="0755555555",
        )
        self.admin_user = User.objects.create_user(username="finance2", password="not-used-in-test")

    def test_rejected_applicant_can_resubmit_a_corrected_payment(self):
        from datetime import date

        from apps.payments.services import initiate_manual_payment, reject_manual_payment, submit_manual_payment

        payment = initiate_manual_payment(
            purpose="REGISTRATION", amount_kes=200, phone_number="0755555555", registration_intent=self.intent,
        )
        first = submit_manual_payment(
            payment=payment, transaction_code="QJI7FIRST01", phone_number_used="0755555555",
            amount_submitted=150, payment_date=date.today(),  # wrong amount, will be rejected
        )
        reject_manual_payment(submission=first, admin_user=self.admin_user, notes="Amount too low.")
        payment.refresh_from_db()
        self.assertEqual(payment.status, "REJECTED")

        # This is the exact scenario the OneToOne bug made impossible —
        # a second submission for the SAME payment must succeed.
        second = submit_manual_payment(
            payment=payment, transaction_code="QJI7SECOND1", phone_number_used="0755555555",
            amount_submitted=200, payment_date=date.today(),
        )
        payment.refresh_from_db()
        self.assertEqual(payment.status, "PENDING_VERIFICATION")
        self.assertEqual(payment.manual_submissions.count(), 2)  # both attempts preserved, not overwritten

        from apps.payments.services import verify_manual_payment
        verify_manual_payment(submission=second, admin_user=self.admin_user, notes="Confirmed on second attempt.")
        payment.refresh_from_db()
        self.assertEqual(payment.status, "PAID")
        # The rejected first attempt's own record is untouched.
        first.refresh_from_db()
        self.assertEqual(first.verification_status, "REJECTED")

    def test_access_token_is_required_to_verify_payment_status(self):
        from apps.payments.services import initiate_manual_payment

        payment = initiate_manual_payment(
            purpose="REGISTRATION", amount_kes=200, phone_number="0755555555", registration_intent=self.intent,
        )
        real_token = payment._raw_access_token
        self.assertTrue(payment.verify_access_token(real_token))
        self.assertFalse(payment.verify_access_token("wrong-token"))
        self.assertFalse(payment.verify_access_token(""))

    def test_access_token_is_never_stored_in_plaintext(self):
        from apps.payments.services import initiate_manual_payment

        payment = initiate_manual_payment(
            purpose="REGISTRATION", amount_kes=200, phone_number="0755555555", registration_intent=self.intent,
        )
        self.assertNotEqual(payment.access_token_hash, payment._raw_access_token)
        self.assertEqual(len(payment.access_token_hash), 64)  # sha256 hex digest length
