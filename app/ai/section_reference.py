"""
Section reference for AI generation.

Compact descriptions of what every section field DOES visually in the viewer.
This is included in AI prompts so the model understands the visual impact of
every toggle, boolean, and option — preventing inconsistencies like writing
"fyll i formuläret nedan" while setting show_form: false.

RULE: Keep this file in sync with viewer components. When a viewer component
gets a new toggle or option, add it here.
"""

SECTION_REFERENCE = """
═══════════════════════════════════════
SEKTIONSREFERENS — VAD VARJE FÄLT GÖR VISUELLT
═══════════════════════════════════════

VIKTIGT: Alla fält nedan styr vad som VISAS på sidan. Om du nämner något i texten
(t.ex. "fyll i formuläret") måste motsvarande toggle vara aktiverad (show_form: true).
Annars syns det inte — och texten ljuger för besökaren.

───────────────────────────────────────
HERO
───────────────────────────────────────
headline: Stor rubrik (max 8 ord, slagkraftigt)
subtitle: Underrubrik under headline (1-2 meningar)
cta: {label, href} — Huvudknapp. href MÅSTE peka på en existerande sida.
background_image: URL till bakgrundsbild. Om null → animerad gradient-bakgrund.
show_cta: true → Visar CTA-knappen. false → Ingen knapp (bara text).
fullscreen: true → Sektionen täcker hela skärmen. false → Mindre höjd (60vh).
show_gradient: true → Animerad gradient med mönster. false → Solid bakgrundsfärg.

───────────────────────────────────────
ABOUT
───────────────────────────────────────
title: Sektionsrubrik (t.ex. "Om oss")
text: Beskrivande text. PÅ STARTSIDAN: kort snippet (40-60 ord). PÅ UNDERSIDA: utförlig (150-250 ord).
image: URL till bild som visas bredvid texten. null → Ingen bild.
highlights: [{label, value}] — Nyckeltal-rutor under texten (t.ex. "15 år", "500+ kunder").
show_highlights: true → Visar highlights-rutorna. false → Döljer dem.
  OBS: Highlights syns BARA på undersida (variant="full"), aldrig på startsidan (snippet).

───────────────────────────────────────
FEATURES
───────────────────────────────────────
title: Sektionsrubrik
subtitle: Underrubrik
items: [{title, description, icon?}] — Varje item visas som ett kort med ikon.
  icon: Valfri emoji som ikon. Om null → automatisk ikon.
  Rekommenderat: 3-5 features.

───────────────────────────────────────
STATS
───────────────────────────────────────
title: Sektionsrubrik (valfri)
items: [{value, label}] — Nyckeltal med stor siffra + etikett.
  value: Siffra som sträng (t.ex. "500+", "15 år", "98%").
  label: Beskrivning (t.ex. "Nöjda kunder").
  Bakgrund: Alltid primärfärg med vit text.

───────────────────────────────────────
SERVICES
───────────────────────────────────────
title: Sektionsrubrik
subtitle: Underrubrik
items: [{title, description}] — Tjänster visade som kort med ikoner.
  PÅ STARTSIDAN: Max 3 visas (snippet). PÅ UNDERSIDA: Alla visas.
  Rekommenderat: 4-6 tjänster.

───────────────────────────────────────
PROCESS
───────────────────────────────────────
title: Sektionsrubrik
subtitle: Underrubrik
steps: [{title, description, step_number}] — Numrerade steg.
  step_number: Siffra som visas i cirkel. Om null → automatisk numrering.
  Visas som tidslinje, kort eller horisontell beroende på stil.
  Rekommenderat: 3-4 steg.

───────────────────────────────────────
GALLERY
───────────────────────────────────────
title: Sektionsrubrik
subtitle: Underrubrik
images: [{url, alt, caption}] — Bildgalleri i rutnät.
  url: MÅSTE vara en verklig bild-URL från listan med tillgängliga bilder.
  PÅ STARTSIDAN: Max 6 bilder visas. PÅ UNDERSIDA: Alla visas.

───────────────────────────────────────
TEAM
───────────────────────────────────────
title: Sektionsrubrik
subtitle: Underrubrik
members: [{name, role, image, bio}] — Teammedlemmar som kort.
  image: URL till profilbild. Om null → visar initial i cirkel.
  bio: Kort biografi (1-2 meningar).

───────────────────────────────────────
TESTIMONIALS
───────────────────────────────────────
title: Sektionsrubrik
items: [{text, author, role}] — Kundomdömen.
  text: Citat (2-3 meningar).
  author: Namn.
  role: Titel/företag.
show_ratings: true → Visar 5-stjärnig betyg ovanför citatet. false → Inga stjärnor.

───────────────────────────────────────
FAQ
───────────────────────────────────────
title: Sektionsrubrik
subtitle: Underrubrik
items: [{question, answer}] — Frågor och svar.
  Visas som dragspel (klicka för att expandera).
  Första frågan är öppen som standard.
  Rekommenderat: 4-6 frågor.

───────────────────────────────────────
CTA (Call-to-Action)
───────────────────────────────────────
title: Stor rubrik (t.ex. "Redo att komma igång?")
text: Kort text (1 mening)
button: {label, href} — CTA-knapp. href MÅSTE peka på existerande sida.
show_button: true → Visar knappen. false → Bara text, ingen knapp.
  REGEL: Sätt ALDRIG show_button: false om du har en button definierad.

───────────────────────────────────────
CONTACT
───────────────────────────────────────
title: Sektionsrubrik (t.ex. "Kontakta oss")
text: Kort beskrivning (1 mening, t.ex. "Vi svarar inom 24 timmar")
show_form: true → Visar kontaktformulär (namn, email, meddelande).
           false → INGET formulär visas.
show_info: true → Visar kontaktkort (email, telefon, adress).
           false → Inga kontaktuppgifter visas.

  VIKTIG REGEL: Om du skriver "fyll i formuläret" i text → MÅSTE show_form vara true.
  VIKTIG REGEL: Om du skriver "ring oss" eller liknande → MÅSTE show_info vara true.
  VIKTIG REGEL: Minst ETT av show_form/show_info bör vara true, annars är sektionen tom.
  OBS: Formuläret kräver att sidan har ett siteId — det fungerar alltid på publicerade sidor.

───────────────────────────────────────
PRICING
───────────────────────────────────────
title: Sektionsrubrik (t.ex. "Priser")
subtitle: Underrubrik
tiers: [{name, price, description, features[], highlighted, cta}]
  name: Paketnamn (t.ex. "Bas", "Premium").
  price: Pris som sträng (t.ex. "299 kr/mån", "Gratis").
  features: Lista med inkluderade funktioner.
  highlighted: true → Sektionen markeras som "Populärast" med ram och skugga.
  cta: {label, href} — Knapp under paketet.
  REGEL: Exakt ETT paket bör ha highlighted: true.

───────────────────────────────────────
VIDEO
───────────────────────────────────────
title: Sektionsrubrik
subtitle: Underrubrik
video_url: YouTube- eller Vimeo-URL. MÅSTE vara giltig URL annars visas inget.
caption: Text under videon.

───────────────────────────────────────
LOGO_CLOUD
───────────────────────────────────────
title: Sektionsrubrik (t.ex. "Våra partners")
subtitle: Underrubrik
logos: [{name, image_url}] — Partnerlogotyper i rad.
  Visas i gråskala, färg vid hover.
  KRÄVER: Verkliga logotyp-URLs. Hittar du inga → använd INTE denna sektion.

───────────────────────────────────────
CUSTOM_CONTENT
───────────────────────────────────────
title: Sektionsrubrik
subtitle: Underrubrik
layout: "one-column" | "two-column" | "three-column" | "grid-2" | "grid-3" | "masonry"
blocks: [{type, content, url, alt, label, href}]
  type: "heading" → Rubrik. content krävs.
  type: "text" → Textblock. content krävs.
  type: "image" → Bild. url + alt krävs.
  type: "button" → Knapp. label + href krävs.

───────────────────────────────────────
BANNER
───────────────────────────────────────
text: Bannertext (kort meddelande)
button: {label, href} — Valfri knapp.
background_color: Hex-färg. Om null → primärfärg.

───────────────────────────────────────
RANKING
───────────────────────────────────────
title: Sektionsrubrik (t.ex. "Topp 5")
subtitle: Underrubrik
items: [{rank, title, description, image, link}]
  rank: Nummer (1, 2, 3...). Topp 3 får speciell styling.
  image: URL. null → ingen bild.
  link: {label, href} — Extern länk/knapp. null → ingen knapp.

───────────────────────────────────────
QUIZ
───────────────────────────────────────
title: Quizrubrik
subtitle: Underrubrik
steps: [{question, options: [{label}]}] — Frågor med alternativ.
results: [{title, description, cta}] — Resultat som visas efter quiz.
result_logic: "score" → Räknar poäng per resultat-index.
  REGEL: Antal results MÅSTE matcha logiken — varje option pekar på ett result-index.
  REGEL: Minst 2 steg och 2 resultat krävs.

═══════════════════════════════════════
NAVIGATION & SIDSTRUKTUR
═══════════════════════════════════════

Navigation genereras AUTOMATISKT från pages-arrayen:
- Varje page med show_in_nav: true visas i headern.
- nav_order styr ordningen (lägre = först).
- Max 8 nav-items visas.
- Installerade appar (blog, bookings) får alltid nav-items.

UNDVIK DUBBLETTER:
- Skapa ALDRIG två sidor med samma syfte (t.ex. "Kontakta oss" + "Boka tid" som båda har kontaktformulär).
- Om kunden vill ha bokning → gör EN sida med slug "kontakt" eller "boka-tid", INTE båda.
- Kontaktsidan kan ha BÅDE formulär (show_form) OCH kontaktinfo (show_info) på samma sida.

CTA-HREFS:
- VARJE href i hela JSON:en MÅSTE peka på en sida som finns.
- Använd page-sluggar: "/om-oss", "/tjanster", "/kontakt".
- Använd "/" för startsidan.
- Externa URLs (https://, mailto:, tel:) är alltid OK.
- ANVÄND ALDRIG ankarlänkar (#section) — de fungerar inte.
"""

# Compact version for per-page prompts (subset of full reference)
SECTION_REFERENCE_COMPACT = """
SEKTIONSFÄLT — VISUELL EFFEKT:
- show_form (contact): true=formulär visas, false=gömt. OM text nämner "fyll i formuläret" → MÅSTE vara true.
- show_info (contact): true=visar email/telefon/adress-kort, false=gömt.
- show_cta (hero): true=visar knapp, false=gömt.
- show_button (cta): true=visar knapp, false=gömt.
- show_highlights (about): true=visar nyckeltal-rutor (bara på full variant).
- show_ratings (testimonials): true=5-stjärnor ovanför citat.
- fullscreen (hero): true=helskärm, false=60% höjd.
- highlighted (pricing tier): true=markeras som "Populärast".

KONSISTENSREGEL: Text och toggles MÅSTE matcha. Om texten säger "kontakta oss via formuläret"
men show_form=false → besökaren ser text om formulär men inget formulär. DET ÄR EN BUGG.
"""
