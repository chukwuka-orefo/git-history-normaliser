from __future__ import annotations

from django.shortcuts import render
from django.http import HttpRequest, HttpResponse

from user_ui.forms import RewriteConfigForm
from user_ui.services import (
    ServiceError,
    preview_yaml,
    run_dry_run,
    run_rewrite,
    browse_repo_directory,
)


def _initial_from_post(post) -> dict:
    initial: dict = {}
    for k, v in post.items():
        if k in ("csrfmiddlewaretoken", "action"):
            continue
        initial[k] = v
    return initial


def index(request: HttpRequest) -> HttpResponse:
    yaml_preview_text: str | None = None
    command_result = None
    action: str | None = None
    browse_error: str | None = None

    if request.method == "POST":
        action = (request.POST.get("action") or "").strip()

        if action == "browse_repo":
            initial = _initial_from_post(request.POST)

            try:
                chosen = browse_repo_directory(initial.get("repo_path"))
                if chosen:
                    initial["repo_path"] = chosen
            except ServiceError as e:
                browse_error = str(e)

            form = RewriteConfigForm(initial=initial)
            context = {
                "form": form,
                "yaml_preview_text": None,
                "command_result": None,
                "action": action,
                "browse_error": browse_error,
            }
            return render(request, "user_ui/index.html", context)

        form = RewriteConfigForm(request.POST)

        if form.is_valid():
            cleaned = form.cleaned_data

            try:
                if action == "preview_yaml":
                    yaml_preview_text = preview_yaml(cleaned)

                elif action == "dry_run":
                    command_result = run_dry_run(cleaned, hash_len=12)

                elif action == "rewrite":
                    if not cleaned.get("confirm_rewrite"):
                        form.add_error(
                            "confirm_rewrite",
                            "You must confirm the rewrite before execution",
                        )
                    else:
                        command_result = run_rewrite(cleaned)

                else:
                    form.add_error(None, "Unknown action")

            except ServiceError as e:
                form.add_error(None, str(e))

        context = {
            "form": form,
            "yaml_preview_text": yaml_preview_text,
            "command_result": command_result,
            "action": action,
            "browse_error": browse_error,
        }
        return render(request, "user_ui/index.html", context)

    form = RewriteConfigForm(
        initial={
            "mode": "author",
            "scope_fraction": 1.0,
        }
    )

    context = {
        "form": form,
        "yaml_preview_text": None,
        "command_result": None,
        "action": None,
        "browse_error": None,
    }
    return render(request, "user_ui/index.html", context)
