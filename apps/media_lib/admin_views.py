from django.contrib import messages
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.accounts.permissions import require_permission
from apps.audit.models import log_action

from .models import MediaAsset
from .validators import validate_image_upload


@require_permission("content.view")
def gallery_list(request):
    """Every published/unpublished asset is its own row here — uploading
    a new one below never touches this list's existing rows or files."""
    images = MediaAsset.objects.filter(category="GALLERY")
    return render(request, "admin_dashboard/media_gallery.html", {"images": images})


@require_permission("media.upload")
@require_POST
def gallery_upload(request):
    files = request.FILES.getlist("images")
    if not files:
        messages.error(request, "Choose at least one image to upload.")
        return redirect("media_lib_admin:gallery")

    created = 0
    for f in files:
        try:
            validate_image_upload(f)
        except ValidationError as exc:
            messages.error(request, f"{f.name}: {exc.message if hasattr(exc, 'message') else exc}")
            continue
        asset = MediaAsset.objects.create(
            file=f, category="GALLERY", caption=request.POST.get("caption", ""),
            alt_text=request.POST.get("alt_text", ""), uploaded_by=request.user,
        )
        log_action("media.upload", request=request, actor=request.user, obj=asset)
        created += 1

    if created:
        messages.success(request, f"Uploaded {created} image(s). Existing images were not affected.")
    return redirect("media_lib_admin:gallery")


@require_permission("media.delete")
@require_POST
def gallery_delete(request, pk):
    asset = get_object_or_404(MediaAsset, pk=pk)
    log_action("media.delete", request=request, actor=request.user, obj=asset, filename=asset.file.name)
    asset.delete()  # only removes THIS row's file — see MediaAsset.delete()
    messages.success(request, "Image deleted.")
    return redirect("media_lib_admin:gallery")


@require_permission("media.upload")
@require_POST
def gallery_toggle_publish(request, pk):
    asset = get_object_or_404(MediaAsset, pk=pk)
    asset.is_published = not asset.is_published
    asset.save(update_fields=["is_published"])
    log_action("media.publish_toggle", request=request, actor=request.user, obj=asset, is_published=asset.is_published)
    return redirect("media_lib_admin:gallery")
