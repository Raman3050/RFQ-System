"""Plain-text + minimal HTML email bodies. All user-supplied values are HTML-escaped."""

from datetime import datetime
from html import escape

from app.email.sender import OutgoingEmail


def _fmt(dt: datetime) -> str:
    return dt.strftime("%d %b %Y, %H:%M UTC")


def _html(paragraphs: list[str], link: str, cta: str) -> str:
    body = "".join(f"<p>{p}</p>" for p in paragraphs)
    return (
        '<div style="font-family:system-ui,sans-serif;max-width:560px;line-height:1.5">'
        f"{body}"
        f'<p><a href="{escape(link)}" style="display:inline-block;padding:10px 18px;'
        f'background:#1f4fd1;color:#fff;border-radius:6px;text-decoration:none">{cta}</a></p>'
        f'<p style="color:#666;font-size:13px">Or open: {escape(link)}</p></div>'
    )


def supplier_account_invite(
    *,
    to: str,
    buyer_name: str,
    buyer_company: str,
    rfq_reference: str,
    rfq_name: str,
    bid_start_at: datetime,
    link: str,
    expires_at: datetime,
) -> OutgoingEmail:
    subject = f"{buyer_company} invited you to quote on {rfq_reference}"
    text = (
        f"{buyer_name} at {buyer_company} has invited you to bid on "
        f"{rfq_reference} — {rfq_name}.\n\n"
        f"Bidding opens {_fmt(bid_start_at)}.\n\n"
        f"Create your supplier account to take part:\n{link}\n\n"
        f"This link expires {_fmt(expires_at)} and can be used once."
    )
    html = _html(
        [
            f"<b>{escape(buyer_name)}</b> at <b>{escape(buyer_company)}</b> has invited you to "
            f"bid on <b>{escape(rfq_reference)}</b> — {escape(rfq_name)}.",
            f"Bidding opens {_fmt(bid_start_at)}.",
            f"This link expires {_fmt(expires_at)} and can be used once.",
        ],
        link,
        "Create supplier account",
    )
    return OutgoingEmail(to, subject, text, html, tags={"kind": "supplier_account_invite"})


def rfq_invitation(
    *,
    to: str,
    buyer_company: str,
    rfq_reference: str,
    rfq_name: str,
    bid_start_at: datetime,
    link: str,
) -> OutgoingEmail:
    subject = f"New RFQ from {buyer_company}: {rfq_reference}"
    text = (
        f"{buyer_company} has invited you to bid on {rfq_reference} — {rfq_name}.\n\n"
        f"Bidding opens {_fmt(bid_start_at)}.\n\nView the RFQ: {link}"
    )
    html = _html(
        [
            f"<b>{escape(buyer_company)}</b> has invited you to bid on "
            f"<b>{escape(rfq_reference)}</b> — {escape(rfq_name)}.",
            f"Bidding opens {_fmt(bid_start_at)}.",
        ],
        link,
        "View RFQ",
    )
    return OutgoingEmail(to, subject, text, html, tags={"kind": "rfq_invitation"})
