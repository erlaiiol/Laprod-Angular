"""
Génération du relevé compta consolidé d'une Structure — PDF récapitulatif des
dépenses LaProd (abonnement + achats de titres) sur une période donnée, destiné
au comptable de la structure. Même stack que invoice_generator.py/royalties_pdf.py
(ReportLab, génération en mémoire, aucune persistance disque) : un relevé est un
rapport à la demande, pas un document contractuel.
"""

import io
from datetime import datetime
from decimal import Decimal
from xml.sax.saxutils import escape as _xml_escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

_C_TEXT    = colors.HexColor('#1a1a1a')
_C_SECTION = colors.HexColor('#2c3e50')
_C_GREEN   = colors.HexColor('#10b981')
_C_MUTED   = colors.HexColor('#6b7280')
_C_BORDER  = colors.HexColor('#d1d5db')

_PAGE_W = A4[0] - 4 * cm


def _esc(value) -> str:
    """Toute donnée utilisateur DOIT passer par ce helper avant d'entrer dans
    un Paragraph — cf. invoice_generator.py."""
    return _xml_escape('' if value is None else str(value))


def _styles():
    base = getSampleStyleSheet()
    return dict(
        title=ParagraphStyle('StTitle', parent=base['Normal'], fontSize=14,
                              textColor=_C_SECTION, fontName='Helvetica-Bold', spaceAfter=2),
        subtitle=ParagraphStyle('StSubtitle', parent=base['Normal'], fontSize=8,
                                 textColor=_C_MUTED, spaceAfter=0),
        label=ParagraphStyle('StLabel', parent=base['Normal'], fontSize=8,
                              textColor=_C_MUTED, fontName='Helvetica-Bold', spaceAfter=1),
        normal=ParagraphStyle('StNormal', parent=base['Normal'], fontSize=9,
                               textColor=_C_TEXT, spaceAfter=2),
        small=ParagraphStyle('StSmall', parent=base['Normal'], fontSize=7.5,
                              textColor=_C_MUTED, spaceAfter=2),
        footer=ParagraphStyle('StFooter', parent=base['Normal'], fontSize=7,
                               textColor=_C_MUTED, alignment=TA_CENTER, spaceAfter=0),
    )


def generate_structure_statement(structure, rows: list[tuple[datetime, str, Decimal]],
                                  period_from: datetime, period_to: datetime) -> bytes:
    """
    structure    : instance Structure (identité facturée)
    rows         : liste de (date, description, montant) déjà triée par date
    period_from/to : bornes de la période couverte
    """
    st = _styles()
    story = []

    generated_at = datetime.now().strftime('%d/%m/%Y à %H:%M')

    header_data = [
        [
            Paragraph('<b>LaProd</b>', st['title']),
            Paragraph(
                'Relevé compta structure',
                ParagraphStyle('StDocR', parent=st['normal'], alignment=TA_RIGHT,
                                fontName='Helvetica-Bold', textColor=_C_SECTION),
            ),
        ],
        [
            Paragraph('Récapitulatif des dépenses LaProd sur la période', st['subtitle']),
            Paragraph(f'Généré le {generated_at}',
                       ParagraphStyle('StDateR', parent=st['small'], alignment=TA_RIGHT)),
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
    story.append(Table([['']], colWidths=[_PAGE_W],
                        style=TableStyle([('LINEBELOW', (0, 0), (0, 0), 1, _C_BORDER)])))
    story.append(Spacer(1, 0.5 * cm))

    story.append(Paragraph('STRUCTURE', st['label']))
    story.append(Paragraph(_esc(structure.name), st['normal']))
    if structure.siret:
        story.append(Paragraph(f'SIRET : {_esc(structure.siret)}', st['small']))
    story.append(Paragraph(
        f"Période : {period_from.strftime('%d/%m/%Y')} — {period_to.strftime('%d/%m/%Y')}",
        st['small'],
    ))
    story.append(Spacer(1, 0.5 * cm))

    table_data = [[
        Paragraph('<b>DATE</b>', ParagraphStyle('ThDate', parent=st['small'], fontName='Helvetica-Bold')),
        Paragraph('<b>DESCRIPTION</b>', ParagraphStyle('ThDesc', parent=st['small'], fontName='Helvetica-Bold')),
        Paragraph('<b>MONTANT</b>', ParagraphStyle('ThAmt', parent=st['small'], fontName='Helvetica-Bold', alignment=TA_RIGHT)),
    ]]

    total = Decimal('0')
    for date, description, amount in rows:
        total += amount
        table_data.append([
            Paragraph(date.strftime('%d/%m/%Y'), st['normal']),
            Paragraph(_esc(description), st['normal']),
            Paragraph(f'{amount} €',
                      ParagraphStyle('Amt', parent=st['normal'], alignment=TA_RIGHT)),
        ])

    table_data.append([
        Paragraph('', st['normal']),
        Paragraph('<b>TOTAL</b>', ParagraphStyle('TotalLbl', parent=st['normal'],
                                                   fontName='Helvetica-Bold', textColor=_C_SECTION)),
        Paragraph(f'<b>{total} €</b>', ParagraphStyle('TotalAmt', parent=st['normal'],
                                                        alignment=TA_RIGHT, fontName='Helvetica-Bold',
                                                        textColor=_C_GREEN)),
    ])

    n = len(table_data)
    t = Table(table_data, colWidths=[_PAGE_W * 0.18, _PAGE_W * 0.57, _PAGE_W * 0.25])
    t.setStyle(TableStyle([
        ('FONTSIZE',      (0, 0), (-1, -1),     9),
        ('BOTTOMPADDING', (0, 0), (-1, -1),     5),
        ('TOPPADDING',    (0, 0), (-1, -1),     4),
        ('VALIGN',        (0, 0), (-1, -1),     'TOP'),
        ('LINEBELOW',     (0, 0), (-1, 0),      0.5, _C_BORDER),
        ('LINEABOVE',     (0, n - 1), (-1, n - 1), 1, _C_SECTION),
        ('BACKGROUND',    (0, n - 1), (-1, n - 1), colors.HexColor('#f8fafc')),
    ]))
    story.append(t)

    story.append(Spacer(1, 0.6 * cm))
    story.append(Table([['']], colWidths=[_PAGE_W],
                        style=TableStyle([('LINEABOVE', (0, 0), (0, 0), 0.5, _C_BORDER)])))
    story.append(Spacer(1, 0.25 * cm))
    story.append(Paragraph(
        "Document généré automatiquement par LaProd à titre récapitulatif. "
        "Les factures détaillées de chaque ligne restent disponibles individuellement "
        "dans votre espace \"Factures\".",
        st['footer'],
    ))

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        leftMargin=2 * cm, rightMargin=2 * cm,
        topMargin=2 * cm, bottomMargin=2 * cm,
    )
    doc.build(story)
    return buf.getvalue()
