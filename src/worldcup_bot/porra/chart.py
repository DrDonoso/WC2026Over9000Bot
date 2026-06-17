"""Porra evolution chart — renders a bump chart of ranking history as a PNG.

Uses matplotlib Agg backend (headless, no display required).
"""

from __future__ import annotations

import matplotlib
matplotlib.use("Agg")  # must be before any pyplot import

import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import logging

log = logging.getLogger(__name__)


def render_evolution_png(history: dict, out_path: str) -> str:
    """Render a bump chart of porra ranking evolution and save as PNG.

    Args:
        history: dict keyed by "YYYY-MM-DD", values are {username: {pos, pts, name}}.
        out_path: filesystem path for the output PNG.

    Returns:
        out_path (for chaining).

    The bump chart shows rank (y, 1 at top, axis inverted) over time (x = sorted dates).
    Handles degenerate cases (0 or 1 checkpoint) gracefully.
    """
    sorted_dates = sorted(history.keys())

    fig, ax = plt.subplots(figsize=(11, 7))

    if not sorted_dates:
        ax.text(0.5, 0.5, "Sin datos todavía", ha="center", va="center",
                transform=ax.transAxes, fontsize=14)
        ax.set_title("Evolución de la porra")
        plt.tight_layout()
        plt.savefig(out_path, dpi=100)
        plt.close(fig)
        return out_path

    # Collect all usernames and their display names
    all_users: set[str] = set()
    for date_data in history.values():
        all_users.update(date_data.keys())

    if not all_users:
        ax.text(0.5, 0.5, "Sin participantes", ha="center", va="center",
                transform=ax.transAxes, fontsize=14)
        ax.set_title("Evolución de la porra")
        plt.tight_layout()
        plt.savefig(out_path, dpi=100)
        plt.close(fig)
        return out_path

    # Build display names — prefer the most recent entry for each user
    display_names: dict[str, str] = {}
    for date in sorted_dates:
        for uname, info in history[date].items():
            display_names[uname] = info.get("name") or uname

    n_users = len(all_users)
    # Use a colormap with enough distinct colours for up to ~20 participants
    cmap = plt.get_cmap("tab20", max(n_users, 1))

    sorted_users = sorted(all_users)
    for i, uname in enumerate(sorted_users):
        dname = display_names.get(uname, uname)
        x_vals: list[int] = []
        y_vals: list[int] = []
        for j, date in enumerate(sorted_dates):
            entry = history[date].get(uname)
            if entry is not None:
                x_vals.append(j)
                y_vals.append(entry["pos"])

        if x_vals:
            ax.plot(
                x_vals, y_vals,
                marker="o", markersize=6,
                label=dname,
                color=cmap(i),
                linewidth=2,
            )

    ax.set_xticks(range(len(sorted_dates)))
    x_labels = [f"{d[8:10]}/{d[5:7]}" for d in sorted_dates]
    ax.set_xticklabels(x_labels, rotation=45, ha="right", fontsize=9)
    ax.invert_yaxis()
    ax.yaxis.set_major_locator(mticker.MaxNLocator(integer=True))
    ax.set_ylabel("Posición", fontsize=11)
    ax.set_xlabel("Jornada", fontsize=11)
    ax.set_title("Evolución de la porra", fontsize=13, pad=12)
    ax.legend(
        loc="upper left",
        bbox_to_anchor=(1.01, 1),
        borderaxespad=0,
        fontsize=9,
        framealpha=0.8,
    )
    ax.grid(axis="y", linestyle="--", alpha=0.4)

    plt.tight_layout()
    plt.savefig(out_path, dpi=100, bbox_inches="tight")
    plt.close(fig)
    return out_path
