"""Stage/player display routes."""

from pathlib import Path

import flask_babel
from flask import jsonify, render_template
from flask_smorest import Blueprint

from biaoke.lib.current_app import get_karaoke_instance, get_site_name

_ = flask_babel.gettext


splash_bp = Blueprint("splash", __name__)

_STATIC_ROOT = Path(__file__).resolve().parents[1] / "static"
_CACHE_BUST_FILES = (
    "vocal-coach.css",
    "vocal-coach.js",
    "images/biaoke-splash-bg.png",
)


def _static_version() -> str:
    """Return a cache-busting token for splash assets."""
    mtimes = []
    for filename in _CACHE_BUST_FILES:
        try:
            mtimes.append(int((_STATIC_ROOT / filename).stat().st_mtime))
        except OSError:
            pass
    return str(max(mtimes, default=1))


def _default_score_phrases() -> dict[str, list[str]]:
    """Translated built-in phrases, used when the user has not set custom ones."""
    return {
        "low": [
            _("Never sing again... ever."),
            _("That was a really good impression of a dying cat!"),
            _("Thank God it's over."),
            _("Pass the mic, please!"),
            _("Well, I'm sure you're very good at your day job."),
        ],
        "mid": [
            _("I've seen better."),
            _("Ok... just ok."),
            _("Not bad for an amateur."),
            _("You put on a decent show."),
            _("That was... something."),
        ],
        "high": [
            _("Congratulations! That was unbelievable!"),
            _("Wow, have you tried auditioning for The Voice?"),
            _("Please, sing another one!"),
            _("You rock! You know that?!"),
            _("Woah, who let Freddie Mercury in here?"),
        ],
    }


def _parse_stored_phrases(stored: str) -> list[str]:
    """Split a stored phrase string on '|' (preferred) or '\\n' (legacy)."""
    sep = "|" if "|" in stored else "\n"
    return [p.strip() for p in stored.split(sep) if p.strip()]


def _get_active_score_phrases(k) -> dict[str, list[str]]:
    """Custom phrases if configured; translated built-in defaults otherwise."""
    defaults = _default_score_phrases()
    result = {}
    for tier in ("low", "mid", "high"):
        stored = getattr(k, f"{tier}_score_phrases")
        result[tier] = (_parse_stored_phrases(stored) if stored else []) or defaults[tier]
    return result


@splash_bp.route("/splash/score_phrases")
def get_score_phrases():
    """Active score phrases as JSON — translated defaults or user-defined custom phrases."""
    return jsonify(_get_active_score_phrases(get_karaoke_instance()))


@splash_bp.route("/palco")
@splash_bp.route("/splash")
@splash_bp.route("/coach")
@splash_bp.route("/splash/coach")
def palco_display():
    """Biaoke stage display for TV output.

    The legacy PiKaraoke splash route remains as an alias so existing kiosk
    links land on the Biaoke stage experience.
    """
    return render_template(
        "vocal_coach.html",
        site_title=get_site_name(),
        title="Palco Biaoke",
        blank_page=True,
        static_version=_static_version(),
    )
