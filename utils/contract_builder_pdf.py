from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Flowable
from reportlab.lib import colors
from reportlab.pdfgen import canvas as rl_canvas

# ── Checkbox dessiné (évite les carrés noirs liés au manque de glyphes Helvetica) ──

class _CheckedBox(Flowable):
    """Case à cocher dessinée avec les primitives ReportLab — jamais de caractère Unicode."""

    _SIZE = 7.5   # pt — taille du carré
    _LW   = 0.7   # pt — épaisseur du trait

    def __init__(self, state: str = 'checked'):
        """
        state : 'checked'   → case cochée  (✓ vert)
                'unchecked' → case vide     (□ neutre)
                'cross'     → case barrée   (✗ gris)  — clause requise mais non activée
        """
        super().__init__()
        self.state = state
        self.width  = self._SIZE + 3
        self.height = self._SIZE + 2

    def draw(self):
        s   = self._SIZE
        c   = self.canv
        lw  = self._LW

        # Fond blanc + contour selon l'état
        if self.state == 'checked':
            fill_col   = colors.HexColor('#edfbf1')
            stroke_col = colors.HexColor('#2a7a4a')
        elif self.state == 'cross':
            fill_col   = colors.HexColor('#fdf0f0')
            stroke_col = colors.HexColor('#999999')
        else:
            fill_col   = colors.white
            stroke_col = colors.HexColor('#aaaaaa')

        c.setLineWidth(lw)
        c.setStrokeColor(stroke_col)
        c.setFillColor(fill_col)
        c.roundRect(1, 1, s, s, 1.5, fill=1, stroke=1)

        if self.state == 'checked':
            # Coche verte (deux segments)
            c.setStrokeColor(colors.HexColor('#1e6e3b'))
            c.setLineWidth(1.3)
            c.setLineCap(1)
            c.line(2.2, s * 0.42, s * 0.42, 2.2)   # trait gauche-bas
            c.line(s * 0.42, 2.2, s - 0.5, s - 0.4) # trait montant
        elif self.state == 'cross':
            c.setStrokeColor(colors.HexColor('#aaaaaa'))
            c.setLineWidth(1.0)
            c.line(2.5, 2.5, s - 1, s - 1)
            c.line(2.5, s - 1, s - 1, 2.5)


def _cb_row(label_para, state: str = 'checked', indent: float = 0) -> Table:
    """Retourne une Table 2-colonnes : [_CheckedBox | Paragraph]."""
    box = _CheckedBox(state=state)
    t = Table(
        [[box, label_para]],
        colWidths=[0.45 * cm, 16.1 * cm - indent],
    )
    t.setStyle(TableStyle([
        ('VALIGN',         (0, 0), (-1, -1), 'MIDDLE'),
        ('LEFTPADDING',    (0, 0), (-1, -1), 0),
        ('RIGHTPADDING',   (0, 0), (-1, -1), 0),
        ('TOPPADDING',     (0, 0), (-1, -1), 1),
        ('BOTTOMPADDING',  (0, 0), (-1, -1), 1),
    ]))
    return t


class _NumberedCanvas(rl_canvas.Canvas):
    """Canvas avec numérotation automatique X/Y et en-tête juridique."""

    def __init__(self, *args, doc_title='', doc_date='', **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states = []
        self._doc_title = doc_title
        self._doc_date  = doc_date

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self._draw_pagination(num_pages)
            super().showPage()
        super().save()

    def _draw_pagination(self, num_pages: int):
        page_w, page_h = A4
        self.saveState()
        self.setFont('Helvetica', 7.5)
        self.setFillColor(colors.HexColor('#888888'))

        # Pied de page — "Page X / Y | Titre | Date"
        footer_y = 0.7 * cm
        self.drawCentredString(
            page_w / 2,
            footer_y,
            f'Page {self._pageNumber} / {num_pages}',
        )
        self.setFont('Helvetica-Oblique', 7)
        if self._doc_title:
            self.drawString(2 * cm, footer_y, self._doc_title[:60])
        if self._doc_date:
            self.drawRightString(page_w - 2 * cm, footer_y, self._doc_date)

        # Ligne de séparation pied
        self.setStrokeColor(colors.HexColor('#dddddd'))
        self.setLineWidth(0.4)
        self.line(2 * cm, footer_y + 0.35 * cm, page_w - 2 * cm, footer_y + 0.35 * cm)

        # En-tête sur les pages suivantes (pas la 1re)
        if self._pageNumber > 1:
            header_y = page_h - 1.3 * cm
            self.setFont('Helvetica-Bold', 7.5)
            self.setFillColor(colors.HexColor('#2c3e50'))
            self.drawString(2 * cm, header_y, 'CONTRAT D\'EXPLOITATION D\'UNE ŒUVRE MUSICALE')
            if self._doc_title:
                self.setFont('Helvetica', 7.5)
                self.setFillColor(colors.HexColor('#555555'))
                self.drawRightString(page_w - 2 * cm, header_y, self._doc_title[:50])
            self.setStrokeColor(colors.HexColor('#dddddd'))
            self.setLineWidth(0.4)
            self.line(2 * cm, header_y - 0.25 * cm, page_w - 2 * cm, header_y - 0.25 * cm)

        self.restoreState()


def generate_custom_contract_pdf(output_path: str, contract_data: dict) -> None:
    """
    Génère un contrat d'exploitation d'oeuvre musicale configurable.

    contract_data = {
        'title': str,
        'generated_at': str (DD/MM/YYYY),
        'parties': [
            {
                'party_type': 'physical' | 'company',
                'role': str,
                # physical
                'first_name': str, 'last_name': str, 'date_of_birth': str,
                'nationality': str, 'pseudonym': str, 'tax_id': str,
                # company
                'company_name': str, 'legal_form': str, 'capital': str,
                'siren': str, 'siret': str, 'rcs': str,
                'legal_rep': str, 'signatory_title': str,
                # common
                'address': str, 'email': str,
            }
        ],
        'sections': [
            {
                'group_name': str,
                'clauses': [
                    {
                        'name': str,
                        'clause_type': str,
                        'value': any,
                        'is_enabled': bool,
                        'legal_reference': str | None,
                    }
                ]
            }
        ]
    }
    """
    doc_title = contract_data.get('title', '')
    doc_date  = contract_data.get('generated_at', '')

    doc = SimpleDocTemplate(
        output_path,
        pagesize=A4,
        leftMargin=2 * cm,
        rightMargin=2 * cm,
        topMargin=2.5 * cm,    # marge haute élargie pour l'en-tête page 2+
        bottomMargin=2.2 * cm, # marge basse élargie pour le pied de page
    )

    story = []
    styles = getSampleStyleSheet()

    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=13,
        textColor=colors.HexColor('#1a1a1a'),
        spaceAfter=20,
        alignment=TA_CENTER,
        fontName='Helvetica-Bold',
    )
    subtitle_style = ParagraphStyle(
        'Subtitle',
        parent=styles['Normal'],
        fontSize=9,
        textColor=colors.HexColor('#666666'),
        alignment=TA_CENTER,
        spaceAfter=30,
    )
    section_style = ParagraphStyle(
        'Section',
        parent=styles['Heading2'],
        fontSize=11,
        textColor=colors.HexColor('#2c3e50'),
        spaceAfter=8,
        spaceBefore=12,
        fontName='Helvetica-Bold',
    )
    normal_style = ParagraphStyle(
        'CustomNormal',
        parent=styles['Normal'],
        fontSize=9.5,
        alignment=TA_JUSTIFY,
        spaceAfter=6,
    )
    label_style = ParagraphStyle(
        'Label',
        parent=styles['Normal'],
        fontSize=9,
        textColor=colors.HexColor('#444444'),
        spaceAfter=3,
        fontName='Helvetica-Bold',
    )
    clause_style = ParagraphStyle(
        'Clause',
        parent=styles['Normal'],
        fontSize=9.5,
        spaceAfter=4,
        leftIndent=12,
    )
    legal_ref_style = ParagraphStyle(
        'LegalRef',
        parent=styles['Normal'],
        fontSize=8,
        textColor=colors.HexColor('#888888'),
        spaceAfter=6,
        leftIndent=12,
        fontName='Helvetica-Oblique',
    )

    # ── Titre ──────────────────────────────────────────────────────────────────
    heading = (contract_data.get('type_label') or "Contrat d'exploitation d'une œuvre musicale").upper()
    story.append(Paragraph(
        heading,
        title_style,
    ))
    story.append(Paragraph(
        f"{contract_data.get('title', '')} — Généré le {contract_data.get('generated_at', '')}",
        subtitle_style,
    ))

    # ── Parties ────────────────────────────────────────────────────────────────
    story.append(Paragraph("<b>ENTRE LES SOUSSIGNÉS :</b>", section_style))

    parties = contract_data.get('parties', [])
    for i, party in enumerate(parties):
        if i > 0:
            story.append(Paragraph("<b>ET</b>", normal_style))
            story.append(Spacer(1, 0.2 * cm))

        if party.get('party_type') == 'company':
            lines = []
            if party.get('company_name'):
                lines.append(f"<b>{party['company_name']}</b>")
            if party.get('legal_form'):
                lines.append(f"Forme juridique : {party['legal_form']}")
            if party.get('capital'):
                lines.append(f"Capital : {party['capital']}")
            if party.get('siren'):
                lines.append(f"SIREN : {party['siren']}")
            if party.get('siret'):
                lines.append(f"SIRET : {party['siret']}")
            if party.get('rcs'):
                lines.append(f"RCS : {party['rcs']}")
            if party.get('address'):
                lines.append(f"Siège social : {party['address']}")
            if party.get('legal_rep'):
                rep_line = f"Représentée par : {party['legal_rep']}"
                if party.get('signatory_title'):
                    rep_line += f", {party['signatory_title']}"
                lines.append(rep_line)
            if party.get('email'):
                lines.append(f"Email : {party['email']}")
        else:
            lines = []
            name_parts = [party.get('first_name', ''), party.get('last_name', '')]
            full_name = ' '.join(p for p in name_parts if p)
            if full_name:
                lines.append(f"<b>{full_name}</b>")
            if party.get('pseudonym'):
                lines.append(f"Nom de scène : {party['pseudonym']}")
            if party.get('date_of_birth'):
                lines.append(f"Né(e) le : {party['date_of_birth']}")
            if party.get('nationality'):
                lines.append(f"Nationalité : {party['nationality']}")
            if party.get('address'):
                lines.append(f"Adresse : {party['address']}")
            if party.get('email'):
                lines.append(f"Email : {party['email']}")
            if party.get('tax_id'):
                lines.append(f"N° fiscal : {party['tax_id']}")

        role = party.get('role', '')
        if role:
            lines.append(f"<i>Ci-après désigné « {role} »</i>")

        story.append(Paragraph('<br/>'.join(lines), normal_style))
        story.append(Spacer(1, 0.3 * cm))

    if len(parties) > 1:
        story.append(Paragraph(
            "Ensemble désignés « les Parties ».",
            normal_style,
        ))
    story.append(Spacer(1, 0.4 * cm))

    # ── Sections de clauses ────────────────────────────────────────────────────
    # La numérotation reflète exactement la logique du front-end :
    #   — articleNumbers : seuls les groupes avec ≥1 clause visible sont numérotés
    #   — clauseNumbers  : seules les clauses visibles reçoivent un sous-numéro

    art_counter = 0
    for section in contract_data.get('sections', []):
        group_name = section.get('group_name', '')
        clauses    = section.get('clauses', [])

        if not clauses:
            continue

        # N'afficher la section que si au moins une clause est active ou required
        visible = [c for c in clauses if c.get('is_enabled') or _is_required(c)]
        if not visible:
            continue

        art_counter += 1
        story.append(Paragraph(
            f"<b>Art. {art_counter} — {group_name.upper()}</b>",
            section_style,
        ))

        clause_counter = 0
        for clause in clauses:
            is_visible = clause.get('is_enabled') or _is_required(clause)
            clause_num = None
            if is_visible:
                clause_counter += 1
                clause_num = clause_counter
            _render_clause(
                story, clause,
                clause_style, label_style, legal_ref_style, normal_style,
                art_num=art_counter, clause_num=clause_num,
            )

        story.append(Spacer(1, 0.2 * cm))

    # ── Signatures ─────────────────────────────────────────────────────────────
    story.append(Spacer(1, 1 * cm))
    story.append(Paragraph("<b>SIGNATURES</b>", section_style))
    story.append(Paragraph(
        "Fait en autant d'originaux que de parties, chacun reconnaissant en avoir reçu un exemplaire.",
        normal_style,
    ))
    story.append(Spacer(1, 0.5 * cm))

    if parties:
        sig_data = [["Fait à : ____________________", "Le : ____________________"]]
        sig_table = Table(sig_data, colWidths=[9 * cm, 7 * cm])
        sig_table.setStyle(TableStyle([('FONTSIZE', (0, 0), (-1, -1), 9)]))
        story.append(sig_table)
        story.append(Spacer(1, 0.8 * cm))

        cols = min(len(parties), 2)
        for chunk_start in range(0, len(parties), cols):
            chunk = parties[chunk_start:chunk_start + cols]
            col_data = []
            for party in chunk:
                if party.get('party_type') == 'company':
                    name = party.get('company_name') or '______________________'
                else:
                    name_parts = [party.get('first_name', ''), party.get('last_name', '')]
                    name = ' '.join(p for p in name_parts if p) or '______________________'
                role = party.get('role', '')
                col_data.append(
                    f"<b>{role}</b><br/>{name}<br/><br/>"
                    "Signature : ________________________<br/><br/>"
                    "Date : ____________________________"
                )
            row = [Paragraph(cell, normal_style) for cell in col_data]
            while len(row) < cols:
                row.append(Paragraph('', normal_style))

            col_width = (17 * cm) / cols
            t = Table([row], colWidths=[col_width] * cols)
            t.setStyle(TableStyle([
                ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                ('LEFTPADDING', (0, 0), (-1, -1), 0),
            ]))
            story.append(t)
            story.append(Spacer(1, 0.8 * cm))

    import functools
    canvas_maker = functools.partial(
        _NumberedCanvas,
        doc_title=doc_title,
        doc_date=doc_date,
    )
    doc.build(story, canvasmaker=canvas_maker)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _is_required(clause: dict) -> bool:
    return clause.get('is_required', False)


def _render_clause(
    story, clause,
    clause_style, label_style, legal_ref_style, normal_style,
    art_num: int | None = None,
    clause_num: int | None = None,
):
    name       = clause.get('name', '')
    ctype      = clause.get('clause_type', 'text')
    value      = clause.get('value')
    is_enabled = clause.get('is_enabled', True)
    legal_ref  = clause.get('legal_reference')
    is_req     = clause.get('is_required', False)

    # Numéro de sous-paragraphe (ex. "3.2 ") — uniquement si les deux sont définis
    num_prefix = f"{art_num}.{clause_num} — " if art_num and clause_num else ""

    # Clauses désactivées et non required → ignorées
    if not is_enabled and not is_req:
        return

    # Clauses required mais non activées → case vide + mention "Non applicable"
    if not is_enabled and is_req:
        story.append(_cb_row(
            Paragraph(f"{num_prefix}<b>{name}</b> — <i>Non applicable</i>", clause_style),
            state='cross',
        ))
        if legal_ref:
            story.append(Paragraph(legal_ref, legal_ref_style))
        return

    if ctype == 'toggle':
        story.append(_cb_row(
            Paragraph(f"{num_prefix}<b>{name}</b>", clause_style),
            state='checked',
        ))

    elif ctype == 'toggle_with_details':
        details = (value or {}).get('details', '') if value else ''
        label   = f"{num_prefix}<b>{name}</b>" + (f" : {details}" if details else "")
        story.append(_cb_row(Paragraph(label, clause_style), state='checked'))

    elif ctype == 'multi_toggle':
        options  = clause.get('options') or []
        selected = set((value or {}).get('selected', []) if value else [])
        story.append(Paragraph(f"{num_prefix}<b>{name}</b>", label_style))
        if options:
            for opt in options:
                state = 'checked' if opt in selected else 'unchecked'
                story.append(_cb_row(
                    Paragraph(opt, clause_style),
                    state=state,
                    indent=0.6 * cm,
                ))
        elif selected:
            # Fallback si options absentes mais selected présent
            for opt in selected:
                story.append(_cb_row(
                    Paragraph(opt, clause_style),
                    state='checked',
                    indent=0.6 * cm,
                ))
        else:
            story.append(Paragraph("<i>Aucun élément sélectionné</i>", clause_style))

    elif ctype in ('text', 'textarea'):
        text = (value or {}).get('text', '') if value else ''
        story.append(Paragraph(f"{num_prefix}<b>{name}</b>", label_style))
        story.append(Paragraph(text if text else "<i>—</i>", clause_style))

    elif ctype == 'number':
        number = (value or {}).get('number', '') if value else ''
        story.append(Paragraph(f"{num_prefix}<b>{name} :</b> {number}", clause_style))

    elif ctype == 'percentage':
        number = (value or {}).get('number', '') if value else ''
        story.append(Paragraph(f"{num_prefix}<b>{name} :</b> {number} %", clause_style))

    elif ctype == 'select':
        selected = (value or {}).get('selected', '') if value else ''
        story.append(_cb_row(
            Paragraph(f"{num_prefix}<b>{name} :</b> {selected}", clause_style),
            state='checked',
        ))

    elif ctype == 'date':
        d = (value or {}).get('date', '') if value else ''
        story.append(Paragraph(f"{num_prefix}<b>{name} :</b> {_fmt_date(d)}", clause_style))

    elif ctype == 'date_range':
        start = _fmt_date((value or {}).get('start', '') if value else '')
        end   = _fmt_date((value or {}).get('end', '') if value else '')
        story.append(Paragraph(f"{num_prefix}<b>{name} :</b> du {start} au {end}", clause_style))

    elif ctype == 'territory':
        territory = (value or {}).get('territory', '') if value else ''
        story.append(Paragraph(f"{num_prefix}<b>{name} :</b> {territory}", clause_style))

    elif ctype == 'duration':
        amount = (value or {}).get('amount', '') if value else ''
        unit   = (value or {}).get('unit', '') if value else ''
        story.append(Paragraph(f"{num_prefix}<b>{name} :</b> {amount} {unit}", clause_style))

    else:
        story.append(Paragraph(f"{num_prefix}<b>{name}</b>", label_style))

    if legal_ref:
        story.append(Paragraph(legal_ref, legal_ref_style))


def _fmt_date(d: str) -> str:
    if not d:
        return '____________________'
    # ISO 8601 → DD/MM/YYYY
    try:
        from datetime import datetime
        return datetime.fromisoformat(d).strftime('%d/%m/%Y')
    except Exception:
        return d
