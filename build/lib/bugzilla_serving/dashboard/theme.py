"""One palette for every dashboard figure."""

PALETTE = [
    "#2563EB",
    "#0D9488",
    "#D97706",
    "#7C3AED",
    "#DC2626",
    "#475569",
    "#65A30D",
    "#DB2777",
    "#0891B2",
]


def style(figure):
    figure.update_layout(
        colorway=PALETTE, template="plotly_white", margin=dict(l=10, r=10, t=40, b=20)
    )
    return figure
