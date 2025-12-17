from __future__ import annotations

from django import forms
from pathlib import Path
import math


MODE_CHOICES = [
    ("author", "Author (repair committer dates)"),
    ("commit", "Commit (accept committer dates)"),
    ("synthetic", "Synthetic (generate new timeline)"),
]


class RewriteConfigForm(forms.Form):
    """
    Canonical UI form for configuring git-history-synth.

    This form:
    - Mirrors the YAML contract exactly
    - Validates UI-level constraints
    - Emits a pure Python structure (no side effects)
    """

    # --------------------------------------------------
    # Repository selection
    # --------------------------------------------------

    repo_path = forms.CharField(
        label="Repository path",
        help_text="Path to a local Git repository",
        widget=forms.TextInput(attrs={"placeholder": "/path/to/repo"}),
    )

    # --------------------------------------------------
    # Mode and scope
    # --------------------------------------------------

    mode = forms.ChoiceField(
        choices=MODE_CHOICES,
        initial="author",
        widget=forms.RadioSelect,
    )

    scope_fraction = forms.FloatField(
        label="Scope fraction",
        initial=1.0,
        min_value=-1.0,
        max_value=1.0,
        help_text="1.0 = all commits, 0.5 = first half, -0.5 = last half",
    )

    # --------------------------------------------------
    # Synthetic: calendar
    # --------------------------------------------------

    calendar_start = forms.DateField(
        required=False,
        label="Start date",
        widget=forms.DateInput(attrs={"type": "date"}),
    )

    calendar_end = forms.DateField(
        required=False,
        label="End date",
        widget=forms.DateInput(attrs={"type": "date"}),
    )

    # Timezone is fixed to UTC for v1
    # Kept explicit for future extension
    calendar_timezone = forms.CharField(
        required=False,
        initial="UTC",
        widget=forms.HiddenInput,
    )

    # --------------------------------------------------
    # Synthetic: work patterns
    # --------------------------------------------------

    weekdays_enabled = forms.BooleanField(required=False, initial=True)
    weekdays_start = forms.TimeField(
        required=False,
        widget=forms.TimeInput(attrs={"type": "time"}),
    )
    weekdays_end = forms.TimeField(
        required=False,
        widget=forms.TimeInput(attrs={"type": "time"}),
    )

    saturday_enabled = forms.BooleanField(required=False)
    saturday_start = forms.TimeField(
        required=False,
        widget=forms.TimeInput(attrs={"type": "time"}),
    )
    saturday_end = forms.TimeField(
        required=False,
        widget=forms.TimeInput(attrs={"type": "time"}),
    )

    sunday_enabled = forms.BooleanField(required=False)
    sunday_start = forms.TimeField(
        required=False,
        widget=forms.TimeInput(attrs={"type": "time"}),
    )
    sunday_end = forms.TimeField(
        required=False,
        widget=forms.TimeInput(attrs={"type": "time"}),
    )

    # --------------------------------------------------
    # Synthetic: randomness (advanced)
    # --------------------------------------------------

    randomness_seed = forms.IntegerField(required=False)
    gap_minutes_min = forms.IntegerField(required=False, min_value=0)
    gap_minutes_max = forms.IntegerField(required=False, min_value=0)
    seconds_min = forms.IntegerField(required=False, min_value=0, max_value=59)
    seconds_max = forms.IntegerField(required=False, min_value=0, max_value=59)

    # --------------------------------------------------
    # Execution intent
    # --------------------------------------------------

    allow_dirty = forms.BooleanField(
        required=False,
        label="Allow dirty working tree",
    )

    confirm_rewrite = forms.BooleanField(
        required=False,
        label="I understand this rewrites Git history",
    )

    # --------------------------------------------------
    # Cross-field validation
    # --------------------------------------------------

    def clean_repo_path(self):
        value = self.cleaned_data["repo_path"]
        path = Path(value).expanduser().resolve()

        if not path.exists():
            raise forms.ValidationError("Path does not exist")

        if not (path / ".git").exists():
            raise forms.ValidationError("Path is not a Git repository")

        return str(path)

    def clean_scope_fraction(self):
        value = self.cleaned_data["scope_fraction"]
        if not math.isfinite(float(value)):
            raise forms.ValidationError("Scope fraction must be a finite number")
        return value

    def clean(self):
        cleaned = super().clean()
        mode = cleaned.get("mode")

        # -----------------------------
        # Author / Commit mode
        # -----------------------------
        if mode in ("author", "commit"):
            # Synthetic fields must be empty. Use "is not None" checks so falsy values like 0 do not slip through.
            synthetic_fields = [
                "calendar_start",
                "calendar_end",
                "weekdays_start",
                "weekdays_end",
                "saturday_start",
                "saturday_end",
                "sunday_start",
                "sunday_end",
                "randomness_seed",
                "gap_minutes_min",
                "gap_minutes_max",
                "seconds_min",
                "seconds_max",
            ]

            for field in synthetic_fields:
                if field in cleaned and cleaned.get(field) is not None:
                    self.add_error(
                        field,
                        "This field is only available in synthetic mode",
                    )

            return cleaned

        # -----------------------------
        # Synthetic mode
        # -----------------------------
        if mode == "synthetic":
            start = cleaned.get("calendar_start")
            end = cleaned.get("calendar_end")

            if start is None:
                self.add_error("calendar_start", "Synthetic mode requires a start date")
            if end is None:
                self.add_error("calendar_end", "Synthetic mode requires an end date")

            if start is not None and end is not None and start > end:
                self.add_error("calendar_end", "End date must be on or after start date")

            # At least one work block must be enabled
            if not (
                cleaned.get("weekdays_enabled")
                or cleaned.get("saturday_enabled")
                or cleaned.get("sunday_enabled")
            ):
                raise forms.ValidationError("At least one work pattern must be enabled")

            self._validate_work_block(
                cleaned,
                "weekdays",
                cleaned.get("weekdays_enabled"),
            )
            self._validate_work_block(
                cleaned,
                "saturday",
                cleaned.get("saturday_enabled"),
            )
            self._validate_work_block(
                cleaned,
                "sunday",
                cleaned.get("sunday_enabled"),
            )

            # Randomness ranges
            gmin = cleaned.get("gap_minutes_min")
            gmax = cleaned.get("gap_minutes_max")
            if gmin is not None and gmax is not None and gmin > gmax:
                self.add_error("gap_minutes_max", "Gap minutes max must be >= min")

            smin = cleaned.get("seconds_min")
            smax = cleaned.get("seconds_max")
            if smin is not None and smax is not None and smin > smax:
                self.add_error("seconds_max", "Seconds max must be >= min")

        return cleaned

    def _validate_work_block(self, cleaned, prefix, enabled):
        if not enabled:
            return

        start_field = f"{prefix}_start"
        end_field = f"{prefix}_end"

        start = cleaned.get(start_field)
        end = cleaned.get(end_field)

        if start is None:
            self.add_error(start_field, f"{prefix.capitalize()} requires a start time")
        if end is None:
            self.add_error(end_field, f"{prefix.capitalize()} requires an end time")

        if start is not None and end is not None and start >= end:
            self.add_error(end_field, f"{prefix.capitalize()} end time must be after start time")
