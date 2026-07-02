"""
Génération de factures PDF pour les transactions LaProd.

Tous les montants monétaires sont manipulés en Decimal (jamais en float)
car les champs SQLAlchemy Numeric(10,2) retournent des Decimal nativement.
"""

import io
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime, timedelta

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

# ─── Constantes financières ───────────────────────────────────────────────────

_PLATFORM_RATE = Decimal('0.10')   # 10% commission LaProd — jamais en float
_Q2            = Decimal('0.01')   # quantize cible : 2 décimales

# ─── Palette de couleurs (cohérente avec contract_generator.py) ───────────────

_C_TEXT    = colors.HexColor('#1a1a1a')
_C_SECTION = colors.HexColor('#2c3e50')
_C_GREEN   = colors.HexColor('#10b981')   # montants positifs
_C_RED     = colors.HexColor('#e74c3c')   # frais / déductions
_C_MUTED   = colors.HexColor('#6b7280')   # texte secondaire
_C_BORDER  = colors.HexColor('#d1d5db')   # séparateurs tableau

# ─── Largeur utile de la page (A4 - marges 2 cm × 2) ─────────────────────────

_PAGE_W = A4[0] - 4 * cm  # ≈ 17,1 cm


# ══════════════════════════════════════════════════════════════════════════════
# Helpers internes
# ══════════════════════════════════════════════════════════════════════════════

def _q(amount: Decimal) -> Decimal:
    """Arrondit à 2 décimales avec ROUND_HALF_UP."""
    return amount.quantize(_Q2, rounding=ROUND_HALF_UP)


def _fmt(amount: Decimal) -> str:
    """Formate un Decimal en chaîne monétaire : '1 234,56 €'."""
    # Séparateur milliers français (espace fine insécable → espace simple pour PDF)
    formatted = f"{amount:,.2f}".replace(',', ' ').replace('.', ',')
    return f"{formatted} €"


def _styles():
    """Crée et retourne le dictionnaire de styles ReportLab."""
    base = getSampleStyleSheet()

    title = ParagraphStyle(
        'InvTitle',
        parent=base['Normal'],
        fontSize=14,
        textColor=_C_SECTION,
        fontName='Helvetica-Bold',
        spaceAfter=2,
    )
    subtitle = ParagraphStyle(
        'InvSubtitle',
        parent=base['Normal'],
        fontSize=8,
        textColor=_C_MUTED,
        spaceAfter=0,
    )
    label = ParagraphStyle(
        'InvLabel',
        parent=base['Normal'],
        fontSize=8,
        textColor=_C_MUTED,
        fontName='Helvetica-Bold',
        spaceAfter=1,
    )
    normal = ParagraphStyle(
        'InvNormal',
        parent=base['Normal'],
        fontSize=9,
        textColor=_C_TEXT,
        spaceAfter=2,
    )
    small = ParagraphStyle(
        'InvSmall',
        parent=base['Normal'],
        fontSize=7.5,
        textColor=_C_MUTED,
        spaceAfter=2,
    )
    footer = ParagraphStyle(
        'InvFooter',
        parent=base['Normal'],
        fontSize=7,
        textColor=_C_MUTED,
        alignment=TA_CENTER,
        spaceAfter=0,
    )
    return dict(title=title, subtitle=subtitle, label=label,
                normal=normal, small=small, footer=footer)


def _header_block(story, st, invoice_num: str, date_str: str, doc_type: str = 'Facture'):
    """
    En-tête commun : nom plateforme à gauche, numéro + date à droite.
    """
    header_data = [
        [
            Paragraph('<b>LaProd</b>', st['title']),
            Paragraph(
                f"<b>{doc_type} n°</b> {invoice_num}",
                ParagraphStyle('InvNumR', parent=st['normal'],
                               alignment=TA_RIGHT, fontName='Helvetica-Bold',
                               textColor=_C_SECTION),
            ),
        ],
        [
            Paragraph('Plateforme musicale indépendante', st['subtitle']),
            Paragraph(
                f"Date : {date_str}",
                ParagraphStyle('InvDateR', parent=st['small'], alignment=TA_RIGHT),
            ),
        ],
        [
            Paragraph('contact@laprod.net', st['subtitle']),
            Paragraph('', st['small']),
        ],
    ]
    t = Table(header_data, colWidths=[_PAGE_W * 0.55, _PAGE_W * 0.45])
    t.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 1),
        ('TOPPADDING', (0, 0), (-1, -1), 1),
    ]))
    story.append(t)
    story.append(Spacer(1, 0.3 * cm))
    # Ligne de séparation
    story.append(Table([['']], colWidths=[_PAGE_W],
                       style=TableStyle([('LINEBELOW', (0, 0), (0, 0), 1, _C_BORDER)])))
    story.append(Spacer(1, 0.4 * cm))


def _parties_block(story, st, emitter_lines: list[str], recipient_lines: list[str]):
    """
    Bloc émetteur / destinataire côte-à-côte.
    """
    def _col(label, lines):
        items = [Paragraph(label, st['label'])]
        for line in lines:
            items.append(Paragraph(line, st['normal']))
        return items

    emitter_col  = _col('ÉMETTEUR', emitter_lines)
    recipient_col = _col('DESTINATAIRE', recipient_lines)

    # On aligne les deux colonnes sur le nombre de lignes max
    max_rows = max(len(emitter_col), len(recipient_col))
    while len(emitter_col)  < max_rows: emitter_col.append(Paragraph('', st['normal']))
    while len(recipient_col) < max_rows: recipient_col.append(Paragraph('', st['normal']))

    data = [[e, r] for e, r in zip(emitter_col, recipient_col)]
    t = Table(data, colWidths=[_PAGE_W * 0.48, _PAGE_W * 0.48],
              spaceBefore=0, spaceAfter=0)
    t.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 1),
        ('TOPPADDING', (0, 0), (-1, -1), 1),
    ]))
    story.append(t)
    story.append(Spacer(1, 0.5 * cm))


def _items_table(story, st, rows: list[tuple[str, Decimal | None, str | None]],
                 total: Decimal, total_label: str = 'TOTAL TTC'):
    """
    Tableau des articles.
    rows : liste de (description, amount, note_optionnelle)
      - Si amount est None → ligne de sous-total ou séparateur visuel
      - Si amount < 0 → affiché en rouge (déduction)
    total : Decimal — affiché en vert en bas
    """
    table_data = [
        [
            Paragraph('<b>DESCRIPTION</b>', ParagraphStyle(
                'ThDesc', parent=st['small'], fontName='Helvetica-Bold')),
            Paragraph('<b>MONTANT</b>', ParagraphStyle(
                'ThAmt', parent=st['small'], fontName='Helvetica-Bold', alignment=TA_RIGHT)),
        ]
    ]

    for desc, amount, note in rows:
        if amount is None:
            # Ligne séparateur / titre de section
            table_data.append([
                Paragraph(f'<b>{desc}</b>', ParagraphStyle(
                    'SecRow', parent=st['small'], fontName='Helvetica-Bold',
                    textColor=_C_SECTION)),
                Paragraph('', st['small']),
            ])
            continue

        color = _C_RED if amount < 0 else _C_TEXT
        desc_cell = Paragraph(desc, st['normal'])
        if note:
            desc_cell = [
                Paragraph(desc, st['normal']),
                Paragraph(note, st['small']),
            ]
        amt_style = ParagraphStyle('Amt', parent=st['normal'],
                                   alignment=TA_RIGHT, textColor=color)
        table_data.append([
            desc_cell,
            Paragraph(_fmt(amount), amt_style),
        ])

    # Ligne total
    table_data.append([
        Paragraph(f'<b>{total_label}</b>', ParagraphStyle(
            'TotalLbl', parent=st['normal'], fontName='Helvetica-Bold',
            textColor=_C_SECTION)),
        Paragraph(f'<b>{_fmt(total)}</b>', ParagraphStyle(
            'TotalAmt', parent=st['normal'], fontName='Helvetica-Bold',
            alignment=TA_RIGHT, textColor=_C_GREEN)),
    ])

    n = len(table_data)
    t = Table(table_data, colWidths=[_PAGE_W * 0.72, _PAGE_W * 0.28])
    t.setStyle(TableStyle([
        ('FONTNAME',      (0, 0), (-1, 0),      'Helvetica-Bold'),
        ('FONTSIZE',      (0, 0), (-1, -1),     9),
        ('BOTTOMPADDING', (0, 0), (-1, -1),     5),
        ('TOPPADDING',    (0, 0), (-1, -1),     4),
        ('VALIGN',        (0, 0), (-1, -1),     'TOP'),
        # Ligne de titre
        ('LINEBELOW',     (0, 0), (-1, 0),      0.5, _C_BORDER),
        # Ligne de total
        ('LINEABOVE',     (0, n - 1), (-1, n - 1), 1, _C_SECTION),
        ('BACKGROUND',    (0, n - 1), (-1, n - 1), colors.HexColor('#f0fdf4')),
    ]))
    story.append(t)


def _stripe_ref(story, st, stripe_id: str | None):
    """Affiche la référence de paiement Stripe si disponible."""
    if stripe_id:
        story.append(Spacer(1, 0.3 * cm))
        story.append(Paragraph(
            f"Référence de paiement : {stripe_id}",
            st['small'],
        ))


def _footer(story, st):
    story.append(Spacer(1, 0.6 * cm))
    story.append(Table([['']], colWidths=[_PAGE_W],
                       style=TableStyle([('LINEABOVE', (0, 0), (0, 0), 0.5, _C_BORDER)])))
    story.append(Spacer(1, 0.25 * cm))
    story.append(Paragraph(
        "Ce document est généré automatiquement et constitue votre justificatif de paiement. "
        "Montants TTC — TVA incluse le cas échéant.",
        st['footer'],
    ))


def _build(build_fn) -> bytes:
    """Génère le PDF en mémoire et retourne les bytes."""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=2 * cm, rightMargin=2 * cm,
        topMargin=2 * cm,  bottomMargin=2 * cm,
    )
    story = []
    st = _styles()
    build_fn(story, st, doc)
    doc.build(story)
    return buf.getvalue()


# ══════════════════════════════════════════════════════════════════════════════
# API publique
# ══════════════════════════════════════════════════════════════════════════════

def generate_track_purchase_invoice(purchase) -> bytes:
    """
    Facture envoyée à l'acheteur d'un beat.
    Tous les montants (purchase.*) sont des Decimal — pas de conversion float.
    """
    def _build_story(story, st, doc):
        year = purchase.created_at.year
        invoice_num = f"LP-{year}-BEAT-{purchase.id:06d}"
        date_str = purchase.created_at.strftime('%d/%m/%Y')

        track    = purchase.track
        buyer    = purchase.buyer_user
        composer = track.composer_user

        _header_block(story, st, invoice_num, date_str)

        _parties_block(
            story, st,
            emitter_lines=[
                'LaProd',
                'Plateforme musicale indépendante',
                'contact@laprod.net',
            ],
            recipient_lines=[
                buyer.username,
                buyer.email,
            ],
        )

        # Lignes de la facture
        fmt_purchased = purchase.format_purchased.upper()
        rows = [
            (
                f'"{track.title}" — Format {fmt_purchased}',
                _q(purchase.track_price),
                f'Compositeur : {composer.username}',
            ),
        ]

        # Licence contractuelle (si > 0)
        if purchase.contract_price and purchase.contract_price > 0:
            territory = getattr(purchase, 'territory', None) or 'France'
            rows.append((
                f'Licence d\'exploitation — {territory}',
                _q(purchase.contract_price),
                None,
            ))

        rows.append((
            'Frais de service LaProd (10 %)',
            _q(purchase.platform_fee),
            None,
        ))

        _items_table(story, st, rows, total=_q(purchase.price_paid))
        _stripe_ref(story, st, purchase.stripe_payment_intent_id)
        _footer(story, st)

    return _build(_build_story)


def generate_track_sale_statement(purchase) -> bytes:
    """
    Relevé de vente envoyé au compositeur.
    Affiche le montant brut, la commission et le net crédité au wallet.
    """
    def _build_story(story, st, doc):
        year = purchase.created_at.year
        invoice_num = f"LP-{year}-BEAT-REV-{purchase.id:06d}"
        date_str = purchase.created_at.strftime('%d/%m/%Y')

        track    = purchase.track
        buyer    = purchase.buyer_user
        composer = track.composer_user

        # Cohérence comptable (assertion silencieuse — logged si off)
        expected = _q(purchase.track_price + (purchase.contract_price or Decimal('0')))

        _header_block(story, st, invoice_num, date_str, doc_type='Relevé de vente')

        _parties_block(
            story, st,
            emitter_lines=['LaProd', 'Plateforme musicale indépendante', 'contact@laprod.net'],
            recipient_lines=[composer.username, composer.email],
        )

        fmt_purchased = purchase.format_purchased.upper()
        available_at = purchase.created_at + timedelta(days=7)

        rows = [
            (
                f'Vente "{track.title}" — Format {fmt_purchased}',
                _q(purchase.price_paid),
                f'Acheteur : {buyer.username}',
            ),
            (
                'Commission LaProd (10 %)',
                -_q(purchase.platform_fee),
                None,
            ),
        ]

        _items_table(
            story, st, rows,
            total=_q(purchase.composer_revenue),
            total_label='NET crédité à votre wallet',
        )

        story.append(Spacer(1, 0.35 * cm))
        story.append(Paragraph(
            f"Fonds disponibles au retrait à partir du : <b>{available_at.strftime('%d/%m/%Y')}</b> "
            f"(délai de 7 jours).",
            st['small'],
        ))
        _footer(story, st)

    return _build(_build_story)


def generate_mixmaster_invoice(mm) -> bytes:
    """
    Facture envoyée à l'artiste lors de la création d'une demande MixMaster.
    Détaille les services sélectionnés et le calendrier de paiement.
    """
    def _build_story(story, st, doc):
        year = mm.created_at.year
        invoice_num = f"LP-{year}-MIX-{mm.id:06d}"
        date_str = mm.created_at.strftime('%d/%m/%Y')

        artist   = mm.artist
        engineer = mm.engineer

        _header_block(story, st, invoice_num, date_str)

        _parties_block(
            story, st,
            emitter_lines=[
                'LaProd',
                'Plateforme musicale indépendante',
                'contact@laprod.net',
            ],
            recipient_lines=[
                artist.username,
                artist.email,
                f'Prestataire : {engineer.username}',
            ],
        )

        # Services sélectionnés
        # Chaque option est un booléen sur mm ; le prix réel est dans mm.total_price
        # On liste les options actives sans recalculer les montants unitaires
        service_lines = [('Services de production', None, None)]   # titre de section
        service_lines.append(('Mix & Master (prestation de base)', None, None))

        options = [
            (mm.service_cleaning,  'Nettoyage des stems (+35 %)'),
            (mm.service_effects,   'Effets & processing (+45 %)'),
            (mm.service_artistic,  'Direction artistique (+60 %)'),
            (mm.service_mastering, 'Mastering (+20 %)'),
            (getattr(mm, 'has_separated_stems', False), 'Stems séparées (+20 %)'),
        ]
        for flag, label in options:
            if flag:
                service_lines.append((f'+ {label}', None, None))

        # Montant total (la vraie source de vérité est mm.total_price)
        service_lines.append(('Total des services', mm.total_price, None))

        # Calendrier de paiement
        schedule_lines = [('Calendrier de paiement', None, None)]
        schedule_lines.append((
            'Acompte réglé à la commande (30 %)',
            _q(mm.deposit_amount),
            'Capturé immédiatement via Stripe',
        ))
        schedule_lines.append((
            'Solde à la livraison finale (70 %)',
            _q(mm.remaining_amount),
            'Capturé après validation de l\'artiste',
        ))

        all_rows = service_lines + [('', None, None)] + schedule_lines

        _items_table(story, st, all_rows, total=_q(mm.total_price))
        _stripe_ref(story, st, getattr(mm, 'stripe_payment_intent_id', None))
        _footer(story, st)

    return _build(_build_story)


def generate_mixmaster_earnings_statement(mm, stage: str) -> bytes:
    """
    Relevé de gains envoyé à l'ingénieur à chaque étape de paiement.
    stage : 'deposit' | 'revision1' | 'revision2' | 'final'

    Calcul des montants (tous en Decimal) :
    - deposit  : mm.deposit_amount (30 % du total)
    - revision : mm.total_price × 10 % par révision
    - final    : mm.remaining_amount − (révisions déjà versées)
    Toujours : net = gross × 0.90  (commission LaProd 10 %)
    """
    STAGE_LABELS = {
        'deposit':   'Acompte initial (30 %)',
        'revision1': 'Révision 1 (10 %)',
        'revision2': 'Révision 2 (10 %)',
        'final':     'Solde final',
    }

    def _gross(stage: str) -> Decimal:
        ten_pct = _q(mm.total_price * Decimal('0.10'))
        if stage == 'deposit':
            return _q(mm.deposit_amount)
        if stage in ('revision1', 'revision2'):
            return ten_pct
        # final : remaining − révisions déjà versées
        revisions_paid = mm.revision_count * ten_pct
        return _q(mm.remaining_amount - revisions_paid)

    def _build_story(story, st, doc):
        year = mm.created_at.year
        stage_label = STAGE_LABELS.get(stage, stage)
        invoice_num = f"LP-{year}-MIX-ENG-{mm.id:06d}"
        date_str = datetime.now().strftime('%d/%m/%Y')

        artist   = mm.artist
        engineer = mm.engineer

        gross = _gross(stage)
        commission = _q(gross * _PLATFORM_RATE)
        net        = _q(gross - commission)

        _header_block(story, st, invoice_num, date_str, doc_type='Relevé de gains')

        _parties_block(
            story, st,
            emitter_lines=['LaProd', 'Plateforme musicale indépendante', 'contact@laprod.net'],
            recipient_lines=[engineer.username, engineer.email],
        )

        story.append(Paragraph(
            f"Mission : Mix & Master pour <b>{artist.username}</b>  —  Étape : <b>{stage_label}</b>",
            st['normal'],
        ))
        story.append(Spacer(1, 0.35 * cm))

        rows = [
            (f'Montant brut — {stage_label}', gross, f'Mission #{mm.id}'),
            ('Commission LaProd (10 %)',       -commission, None),
        ]

        _items_table(
            story, st, rows,
            total=net,
            total_label='NET crédité à votre wallet',
        )

        story.append(Spacer(1, 0.35 * cm))
        available_at = datetime.now() + timedelta(days=7)
        story.append(Paragraph(
            f"Fonds disponibles au retrait à partir du : <b>{available_at.strftime('%d/%m/%Y')}</b> "
            f"(délai de 7 jours).",
            st['small'],
        ))
        _footer(story, st)

    return _build(_build_story)
