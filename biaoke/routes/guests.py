"""Guest list routes."""

from __future__ import annotations

from flask import Blueprint, flash, redirect, render_template, request, url_for

from biaoke.lib.current_app import get_karaoke_instance, get_site_name

guests_bp = Blueprint("guests", __name__)


@guests_bp.route("/guests", methods=["GET"])
def guests():
    """Render the guest management page."""
    k = get_karaoke_instance()
    return render_template(
        "guests.html",
        site_title=get_site_name(),
        title="Guests",
        guests=k.guest_manager.list_guests(),
    )


@guests_bp.route("/guests", methods=["POST"])
def add_guest():
    """Add a guest name."""
    k = get_karaoke_instance()
    ok, message = k.guest_manager.add_guest(request.form.get("name", ""))
    flash(message, "is-success" if ok else "is-danger")
    return redirect(url_for("guests.guests"))


@guests_bp.route("/guests/delete", methods=["POST"])
def delete_guest():
    """Remove a guest name."""
    k = get_karaoke_instance()
    ok, message = k.guest_manager.remove_guest(request.form.get("name", ""))
    flash(message, "is-warning" if ok else "is-danger")
    return redirect(url_for("guests.guests"))
