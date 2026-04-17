"""
Email templates for Qvicko.

Outreach emails are plain text only (to appear hand-written).
All other templates share a unified HTML design based on the frontend palette:
  Background (sand mist): #FDFAF5
  Primary (petrol blue):  #326586
  Primary dark:           #24506E
  Text (primary deep):    #1A3A50
  Accent:                 #F4E9D4
  Surface:                #FFFFFF
  Border:                 #E0D8CB
  Border light:           #EDE7DC
  Text secondary:         #4A7A96
  Text muted:             #7A9BAD
"""

from __future__ import annotations

from html import escape as html_escape


# ---------------------------------------------------------------------------
# Shared layout helpers
# ---------------------------------------------------------------------------

def _wrap_layout(inner_html: str) -> str:
    """Wrap content in the shared email layout."""
    return f"""<!DOCTYPE html>
<html lang="sv">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
</head>
<body style="margin:0; padding:0; background-color:#FDFAF5; font-family:'Segoe UI',Roboto,Helvetica,Arial,sans-serif; -webkit-font-smoothing:antialiased;">
  <table width="100%" cellpadding="0" cellspacing="0" role="presentation" style="background-color:#FDFAF5; padding:40px 20px;">
    <tr><td align="center">
      <table width="560" cellpadding="0" cellspacing="0" role="presentation" style="max-width:560px; width:100%; background:#FFFFFF; border-radius:16px; border:1px solid #E0D8CB; overflow:hidden;">

        <!-- Header -->
        <tr><td style="background:#326586; padding:28px 40px; text-align:center;">
          <span style="color:#FFFFFF; font-size:24px; font-weight:700; letter-spacing:0.5px;">Qvicko</span>
        </td></tr>

        <!-- Body -->
        <tr><td style="padding:40px;">
{inner_html}
        </td></tr>

        <!-- Footer -->
        <tr><td style="padding:20px 40px; border-top:1px solid #EDE7DC; text-align:center;">
          <p style="color:#7A9BAD; font-size:12px; margin:0;">
            &copy; 2026 Qvicko. Alla r&auml;ttigheter f&ouml;rbeh&aring;llna.
          </p>
        </td></tr>

      </table>
    </td></tr>
  </table>
</body>
</html>"""


def _cta_button(url: str, label: str) -> str:
    """Render a centred CTA button in petrol blue."""
    return f"""          <table width="100%" cellpadding="0" cellspacing="0" role="presentation">
            <tr><td align="center" style="padding:8px 0;">
              <a href="{url}" style="display:inline-block; background:#326586; color:#FFFFFF; text-decoration:none; padding:14px 36px; border-radius:12px; font-size:15px; font-weight:600;">
                {label}
              </a>
            </td></tr>
          </table>"""


def _info_box(text: str) -> str:
    """Render a sand-mist info box with accent background."""
    return f"""          <table width="100%" cellpadding="0" cellspacing="0" role="presentation">
            <tr><td style="background:#F4E9D4; border-radius:12px; padding:20px 24px; border:1px solid #E0D8CB;">
              <p style="color:#1A3A50; font-size:14px; line-height:1.6; margin:0;">
                {text}
              </p>
            </td></tr>
          </table>"""


# ---------------------------------------------------------------------------
# 1. Outreach email (plain text only — looks hand-written)
# ---------------------------------------------------------------------------

def build_outreach_email(
    business_name: str,
    demo_url: str,
    from_name: str = "Qvicko",
) -> tuple[str, str, str]:
    """
    Build subject, html_body, and plain_text for an outreach email.
    Returns (subject, html_body, plain_text).

    NOTE: html_body is intentionally minimal — plain text is the primary
    format so the email looks personally written, not templated.
    """
    subject = f"{business_name} — vi har skapat ett förslag på en ny hemsida åt er"
    subject = subject.replace("\n", "").replace("\r", "")

    plain_text = (
        f"Hej {business_name}!\n"
        f"\n"
        f"Jag hittade er hemsida och såg att det finns potential att modernisera den.\n"
        f"Därför tog jag mig friheten att skapa ett förslag på hur en ny, modern\n"
        f"hemsida skulle kunna se ut för er.\n"
        f"\n"
        f"Jag har utgått från ert befintliga innehåll, era färger och er profil\n"
        f"för att skapa något som känns rätt för just ert företag.\n"
        f"\n"
        f"Kolla in förslaget här: {demo_url}\n"
        f"\n"
        f"Förslaget är helt kostnadsfritt och utan förpliktelser. Om ni gillar det\n"
        f"kan vi prata vidare om hur jag kan hjälpa er att komma igång.\n"
        f"\n"
        f"Hör gärna av er om ni har frågor!\n"
        f"\n"
        f"Vänliga hälsningar,\n"
        f"{from_name}"
    )

    # Minimal HTML — just wraps the plain text so it renders fine in all clients
    html_body = (
        f"<div style=\"font-family:sans-serif; font-size:14px; color:#222; line-height:1.6;\">"
        f"<p>Hej {html_escape(business_name)}!</p>"
        f"<p>Jag hittade er hemsida och s&aring;g att det finns potential att modernisera den. "
        f"D&auml;rf&ouml;r tog jag mig friheten att skapa ett f&ouml;rslag p&aring; hur en ny, modern "
        f"hemsida skulle kunna se ut f&ouml;r er.</p>"
        f"<p>Jag har utg&aring;tt fr&aring;n ert befintliga inneh&aring;ll, era f&auml;rger och er profil "
        f"f&ouml;r att skapa n&aring;got som k&auml;nns r&auml;tt f&ouml;r just ert f&ouml;retag.</p>"
        f"<p>Kolla in f&ouml;rslaget h&auml;r: <a href=\"{html_escape(demo_url)}\">{html_escape(demo_url)}</a></p>"
        f"<p>F&ouml;rslaget &auml;r helt kostnadsfritt och utan f&ouml;rpliktelser. Om ni gillar det "
        f"kan vi prata vidare om hur jag kan hj&auml;lpa er att komma ig&aring;ng.</p>"
        f"<p>H&ouml;r g&auml;rna av er om ni har fr&aring;gor!</p>"
        f"<p>V&auml;nliga h&auml;lsningar,<br>{html_escape(from_name)}</p>"
        f"</div>"
    )

    return subject, html_body, plain_text


# ---------------------------------------------------------------------------
# 2. Password reset email
# ---------------------------------------------------------------------------

def build_password_reset_email(
    reset_url: str,
    user_name: str = "användare",
) -> tuple[str, str, str]:
    safe_name = html_escape(user_name)
    safe_url = html_escape(reset_url)

    subject = "Återställ ditt lösenord — Qvicko"

    inner = f"""          <h2 style="color:#1A3A50; margin:0 0 16px; font-size:22px;">&Aring;terst&auml;ll ditt l&ouml;senord</h2>

          <p style="color:#1A3A50; font-size:15px; line-height:1.6; margin:0 0 12px;">
            Hej {safe_name},
          </p>

          <p style="color:#4A7A96; font-size:15px; line-height:1.6; margin:0 0 28px;">
            Vi har f&aring;tt en beg&auml;ran om att &aring;terst&auml;lla l&ouml;senordet f&ouml;r ditt konto.
            Klicka p&aring; knappen nedan f&ouml;r att v&auml;lja ett nytt l&ouml;senord.
            L&auml;nken &auml;r giltig i 30&nbsp;minuter.
          </p>

{_cta_button(safe_url, "&Aring;terst&auml;ll l&ouml;senord")}

          <p style="color:#7A9BAD; font-size:13px; line-height:1.5; margin:28px 0 0;">
            Om du inte beg&auml;rde detta kan du ignorera detta meddelande.
          </p>

          <p style="color:#7A9BAD; font-size:12px; margin:16px 0 0; word-break:break-all;">
            Eller kopiera denna l&auml;nk: {safe_url}
          </p>"""

    html_body = _wrap_layout(inner)

    plain_text = f"""Hej {user_name},

Vi har fått en begäran om att återställa lösenordet för ditt konto. Klicka på länken nedan för att välja ett nytt lösenord. Länken är giltig i 30 minuter.

Återställ lösenord: {reset_url}

Om du inte begärde detta kan du ignorera detta meddelande.

— Qvicko"""

    return subject, html_body, plain_text


# ---------------------------------------------------------------------------
# 3. Email verification
# ---------------------------------------------------------------------------

def build_verification_email(
    verify_url: str,
    user_name: str = "användare",
) -> tuple[str, str, str]:
    safe_name = html_escape(user_name)
    safe_url = html_escape(verify_url)

    subject = "Verifiera din e-postadress — Qvicko"

    inner = f"""          <h2 style="color:#1A3A50; margin:0 0 16px; font-size:22px;">Verifiera din e-postadress</h2>

          <p style="color:#1A3A50; font-size:15px; line-height:1.6; margin:0 0 12px;">
            Hej {safe_name},
          </p>

          <p style="color:#4A7A96; font-size:15px; line-height:1.6; margin:0 0 28px;">
            Tack f&ouml;r att du skapade ett konto hos Qvicko!
            Klicka p&aring; knappen nedan f&ouml;r att verifiera din e-postadress och aktivera ditt konto.
            L&auml;nken &auml;r giltig i 24&nbsp;timmar.
          </p>

{_cta_button(safe_url, "Verifiera e-post")}

          <p style="color:#7A9BAD; font-size:13px; line-height:1.5; margin:28px 0 0;">
            Om du inte skapade ett konto kan du ignorera detta meddelande.
          </p>

          <p style="color:#7A9BAD; font-size:12px; margin:16px 0 0; word-break:break-all;">
            Eller kopiera denna l&auml;nk: {safe_url}
          </p>"""

    html_body = _wrap_layout(inner)

    plain_text = f"""Hej {user_name},

Tack för att du skapade ett konto hos Qvicko! Klicka på länken nedan för att verifiera din e-postadress och aktivera ditt konto. Länken är giltig i 24 timmar.

Verifiera e-post: {verify_url}

Om du inte skapade ett konto kan du ignorera detta meddelande.

— Qvicko"""

    return subject, html_body, plain_text


# ---------------------------------------------------------------------------
# 4. Site published — welcome (day 0)
# ---------------------------------------------------------------------------

def build_site_published_email(
    user_name: str,
    business_name: str,
    site_url: str,
    dashboard_url: str,
) -> tuple[str, str, str]:
    safe_name = html_escape(user_name)
    safe_biz = html_escape(business_name)
    safe_site = html_escape(site_url)
    safe_dash = html_escape(dashboard_url)

    subject = f"Er hemsida är live — {business_name}"

    inner = f"""          <h2 style="color:#1A3A50; margin:0 0 16px; font-size:22px;">Er hemsida &auml;r live!</h2>

          <p style="color:#1A3A50; font-size:15px; line-height:1.6; margin:0 0 12px;">
            Hej {safe_name},
          </p>

          <p style="color:#4A7A96; font-size:15px; line-height:1.6; margin:0 0 24px;">
            Grattis! Hemsidan f&ouml;r <strong>{safe_biz}</strong> &auml;r nu publicerad och tillg&auml;nglig f&ouml;r bes&ouml;kare.
          </p>

{_info_box(
    f"<strong>Gratis i 30 dagar</strong> &mdash; er hemsida &auml;r kostnadsfri de f&ouml;rsta 30 dagarna. "
    f"F&ouml;r att beh&aring;lla den efter det beh&ouml;ver ni koppla en betalningsmetod. "
    f"Om ingen betalning registreras tas hemsidan bort efter 45 dagar."
)}

          <div style="height:24px;"></div>

{_cta_button(safe_site, "Bes&ouml;k er hemsida")}

          <p style="color:#4A7A96; font-size:14px; line-height:1.6; margin:28px 0 0;">
            Logga in p&aring; <a href="{safe_dash}" style="color:#326586; text-decoration:underline;">ert konto</a> f&ouml;r att hantera hemsidan, koppla en egen dom&auml;n eller l&auml;gga till en betalningsmetod.
          </p>"""

    html_body = _wrap_layout(inner)

    plain_text = f"""Hej {user_name},

Grattis! Hemsidan för {business_name} är nu publicerad och tillgänglig för besökare.

Besök er hemsida: {site_url}

GRATIS I 30 DAGAR — er hemsida är kostnadsfri de första 30 dagarna. För att behålla den efter det behöver ni koppla en betalningsmetod. Om ingen betalning registreras tas hemsidan bort efter 45 dagar.

Logga in på ert konto för att hantera hemsidan: {dashboard_url}

— Qvicko"""

    return subject, html_body, plain_text


# ---------------------------------------------------------------------------
# 5. Free trial ending soon (day ~25)
# ---------------------------------------------------------------------------

def build_trial_ending_email(
    user_name: str,
    business_name: str,
    days_left: int,
    dashboard_url: str,
) -> tuple[str, str, str]:
    safe_name = html_escape(user_name)
    safe_biz = html_escape(business_name)
    safe_dash = html_escape(dashboard_url)

    subject = f"Er gratis period går ut om {days_left} dagar — {business_name}"

    inner = f"""          <h2 style="color:#1A3A50; margin:0 0 16px; font-size:22px;">Er gratis period g&aring;r snart ut</h2>

          <p style="color:#1A3A50; font-size:15px; line-height:1.6; margin:0 0 12px;">
            Hej {safe_name},
          </p>

          <p style="color:#4A7A96; font-size:15px; line-height:1.6; margin:0 0 24px;">
            Den kostnadsfria perioden f&ouml;r <strong>{safe_biz}</strong> g&aring;r ut om <strong>{days_left}&nbsp;dagar</strong>.
            F&ouml;r att er hemsida ska forts&auml;tta vara tillg&auml;nglig beh&ouml;ver ni koppla en betalningsmetod.
          </p>

{_info_box(
    f"Om ingen betalningsmetod kopplas inom 30 dagar fr&aring;n publiceringen "
    f"pausas hemsidan. Efter ytterligare 15 dagar raderas den permanent."
)}

          <div style="height:24px;"></div>

{_cta_button(safe_dash, "Koppla betalningsmetod")}

          <p style="color:#7A9BAD; font-size:13px; line-height:1.5; margin:28px 0 0;">
            Har ni fr&aring;gor? Svara p&aring; detta mail s&aring; hj&auml;lper vi er.
          </p>"""

    html_body = _wrap_layout(inner)

    plain_text = f"""Hej {user_name},

Den kostnadsfria perioden för {business_name} går ut om {days_left} dagar. För att er hemsida ska fortsätta vara tillgänglig behöver ni koppla en betalningsmetod.

Om ingen betalningsmetod kopplas inom 30 dagar från publiceringen pausas hemsidan. Efter ytterligare 15 dagar raderas den permanent.

Koppla betalningsmetod: {dashboard_url}

Har ni frågor? Svara på detta mail så hjälper vi er.

— Qvicko"""

    return subject, html_body, plain_text


# ---------------------------------------------------------------------------
# 6. Site paused — free period expired (day 30)
# ---------------------------------------------------------------------------

def build_site_paused_email(
    user_name: str,
    business_name: str,
    days_until_deletion: int,
    dashboard_url: str,
) -> tuple[str, str, str]:
    safe_name = html_escape(user_name)
    safe_biz = html_escape(business_name)
    safe_dash = html_escape(dashboard_url)

    subject = f"Er hemsida har pausats — {business_name}"

    inner = f"""          <h2 style="color:#1A3A50; margin:0 0 16px; font-size:22px;">Er hemsida har pausats</h2>

          <p style="color:#1A3A50; font-size:15px; line-height:1.6; margin:0 0 12px;">
            Hej {safe_name},
          </p>

          <p style="color:#4A7A96; font-size:15px; line-height:1.6; margin:0 0 24px;">
            Den kostnadsfria perioden f&ouml;r <strong>{safe_biz}</strong> har g&aring;tt ut.
            Er hemsida &auml;r inte l&auml;ngre synlig f&ouml;r bes&ouml;kare.
          </p>

{_info_box(
    f"<strong>Hemsidan raderas om {days_until_deletion} dagar.</strong> "
    f"Koppla en betalningsmetod innan dess f&ouml;r att &aring;teraktivera den."
)}

          <div style="height:24px;"></div>

{_cta_button(safe_dash, "Koppla betalningsmetod")}

          <p style="color:#7A9BAD; font-size:13px; line-height:1.5; margin:28px 0 0;">
            Har ni fr&aring;gor? Svara p&aring; detta mail s&aring; hj&auml;lper vi er.
          </p>"""

    html_body = _wrap_layout(inner)

    plain_text = f"""Hej {user_name},

Den kostnadsfria perioden för {business_name} har gått ut. Er hemsida är inte längre synlig för besökare.

Hemsidan raderas om {days_until_deletion} dagar. Koppla en betalningsmetod innan dess för att återaktivera den.

Koppla betalningsmetod: {dashboard_url}

Har ni frågor? Svara på detta mail så hjälper vi er.

— Qvicko"""

    return subject, html_body, plain_text


# ---------------------------------------------------------------------------
# 7. Final warning — site about to be deleted (day ~42)
# ---------------------------------------------------------------------------

def build_site_deletion_warning_email(
    user_name: str,
    business_name: str,
    days_until_deletion: int,
    dashboard_url: str,
) -> tuple[str, str, str]:
    safe_name = html_escape(user_name)
    safe_biz = html_escape(business_name)
    safe_dash = html_escape(dashboard_url)

    subject = f"Sista chansen — er hemsida raderas om {days_until_deletion} dagar"

    inner = f"""          <h2 style="color:#1A3A50; margin:0 0 16px; font-size:22px;">Er hemsida raderas snart</h2>

          <p style="color:#1A3A50; font-size:15px; line-height:1.6; margin:0 0 12px;">
            Hej {safe_name},
          </p>

          <p style="color:#4A7A96; font-size:15px; line-height:1.6; margin:0 0 24px;">
            Hemsidan f&ouml;r <strong>{safe_biz}</strong> kommer att <strong>raderas permanent
            om {days_until_deletion}&nbsp;dagar</strong> om ingen betalningsmetod kopplas.
          </p>

          <table width="100%" cellpadding="0" cellspacing="0" role="presentation">
            <tr><td style="background:#FDF0F0; border-radius:12px; padding:20px 24px; border:1px solid #E0D8CB;">
              <p style="color:#C44D4D; font-size:14px; line-height:1.6; margin:0;">
                <strong>Detta g&aring;r inte att &aring;ngra.</strong> N&auml;r hemsidan &auml;r raderad f&ouml;rsvinner allt inneh&aring;ll, dom&auml;nkopplingar och statistik.
              </p>
            </td></tr>
          </table>

          <div style="height:24px;"></div>

{_cta_button(safe_dash, "Koppla betalningsmetod nu")}

          <p style="color:#7A9BAD; font-size:13px; line-height:1.5; margin:28px 0 0;">
            Har ni fr&aring;gor? Svara p&aring; detta mail s&aring; hj&auml;lper vi er.
          </p>"""

    html_body = _wrap_layout(inner)

    plain_text = f"""Hej {user_name},

Hemsidan för {business_name} kommer att RADERAS PERMANENT om {days_until_deletion} dagar om ingen betalningsmetod kopplas.

Detta går inte att ångra. När hemsidan är raderad försvinner allt innehåll, domänkopplingar och statistik.

Koppla betalningsmetod nu: {dashboard_url}

Har ni frågor? Svara på detta mail så hjälper vi er.

— Qvicko"""

    return subject, html_body, plain_text


# ---------------------------------------------------------------------------
# 8. Site deleted (day 45)
# ---------------------------------------------------------------------------

def build_site_deleted_email(
    user_name: str,
    business_name: str,
) -> tuple[str, str, str]:
    safe_name = html_escape(user_name)
    safe_biz = html_escape(business_name)

    subject = f"Er hemsida har raderats — {business_name}"

    inner = f"""          <h2 style="color:#1A3A50; margin:0 0 16px; font-size:22px;">Er hemsida har raderats</h2>

          <p style="color:#1A3A50; font-size:15px; line-height:1.6; margin:0 0 12px;">
            Hej {safe_name},
          </p>

          <p style="color:#4A7A96; font-size:15px; line-height:1.6; margin:0 0 24px;">
            Hemsidan f&ouml;r <strong>{safe_biz}</strong> har nu raderats d&aring; ingen betalningsmetod kopplades inom tidsfristen.
          </p>

          <p style="color:#4A7A96; font-size:15px; line-height:1.6; margin:0 0 16px;">
            Allt inneh&aring;ll, dom&auml;nkopplingar och statistik har tagits bort permanent.
          </p>

          <p style="color:#4A7A96; font-size:15px; line-height:1.6; margin:0;">
            Om ni vill ha en ny hemsida i framtiden &auml;r ni varmt v&auml;lkomna tillbaka.
            H&ouml;r av er s&aring; hj&auml;lper vi er!
          </p>"""

    html_body = _wrap_layout(inner)

    plain_text = f"""Hej {user_name},

Hemsidan för {business_name} har nu raderats då ingen betalningsmetod kopplades inom tidsfristen.

Allt innehåll, domänkopplingar och statistik har tagits bort permanent.

Om ni vill ha en ny hemsida i framtiden är ni varmt välkomna tillbaka. Hör av er så hjälper vi er!

— Qvicko"""

    return subject, html_body, plain_text


# ---------------------------------------------------------------------------
# 9. Payment method added confirmation
# ---------------------------------------------------------------------------

def build_payment_method_added_email(
    user_name: str,
    business_name: str,
    dashboard_url: str,
) -> tuple[str, str, str]:
    safe_name = html_escape(user_name)
    safe_biz = html_escape(business_name)
    safe_dash = html_escape(dashboard_url)

    subject = f"Betalningsmetod kopplad — {business_name}"

    inner = f"""          <h2 style="color:#1A3A50; margin:0 0 16px; font-size:22px;">Betalningsmetod kopplad!</h2>

          <p style="color:#1A3A50; font-size:15px; line-height:1.6; margin:0 0 12px;">
            Hej {safe_name},
          </p>

          <p style="color:#4A7A96; font-size:15px; line-height:1.6; margin:0 0 24px;">
            En betalningsmetod har kopplats till hemsidan f&ouml;r <strong>{safe_biz}</strong>.
            Er hemsida &auml;r nu s&auml;krad och kommer att forts&auml;tta vara tillg&auml;nglig.
          </p>

{_info_box(
    "Ni kan n&auml;r som helst &auml;ndra betalningsmetod eller se er fakturering i kontrollpanelen."
)}

          <div style="height:24px;"></div>

{_cta_button(safe_dash, "G&aring; till kontrollpanelen")}"""

    html_body = _wrap_layout(inner)

    plain_text = f"""Hej {user_name},

En betalningsmetod har kopplats till hemsidan för {business_name}. Er hemsida är nu säkrad och kommer att fortsätta vara tillgänglig.

Ni kan när som helst ändra betalningsmetod eller se er fakturering i kontrollpanelen: {dashboard_url}

— Qvicko"""

    return subject, html_body, plain_text
