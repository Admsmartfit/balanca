"""Geração automática de PDF do resultado de uma medição.

Gerado no servidor assim que uma medição é persistida (sem depender de
mouse/toque no quiosque — ver ``app/server.py``). O envio do PDF (e-mail,
WhatsApp etc.) fica para uma etapa futura; por enquanto ele só é salvo em
disco e fica disponível para download pelo painel administrativo.

O layout segue o padrão de laudo de bioimpedância mais familiar ao usuário
final (ex.: InBody): bloco de identificação, tabela "Composição Corporal"
por massa (kg), e barras horizontais de faixa abaixo/normal/acima para as
métricas que têm uma faixa de referência validada (ver
``engine/reference_ranges.py``). Métricas sem faixa validada (água, massa
óssea, proteína, BMR, idade metabólica) aparecem como número simples — não
inventamos limiares novos só para preencher um medidor.
"""

from __future__ import annotations

import io
from datetime import datetime, timezone
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Flowable, KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from .config import ROOT_DIR
from .db import Client
from .engine import BodyMetricsInput
from .engine.reference_ranges import BMI_HIGH, BMI_LOW, reference_ranges_for

REPORTS_DIR = ROOT_DIR / "data" / "reports"

_BRAND_TEAL = colors.HexColor("#0e7a78")
_TRACK_GREY = colors.HexColor("#eef1f0")
_TRACK_BORDER = colors.HexColor("#c7cdd1")
_STATUS_COLORS = {
    "Abaixo": colors.HexColor("#c98a1f"),
    "Normal": _BRAND_TEAL,
    "Acima": colors.HexColor("#c0392b"),
}

_METRIC_INFO = {
    "bmi": ("IMC", "", 1),
    "fat_percentage": ("Gordura corporal", "%", 1),
    "water_percentage": ("Água corporal", "%", 1),
    "bone_mass_kg": ("Massa óssea", "kg", 2),
    "muscle_mass_kg": ("Massa muscular", "kg", 1),
    "visceral_fat": ("Gordura visceral", "", 1),
    "bmr_kcal": ("Taxa metabólica basal", "kcal", 0),
    "metabolic_age": ("Idade metabólica", "anos", 0),
    "protein_percentage": ("Proteína", "%", 1),
}

_SEX_LABELS = {"male": "Masculino", "female": "Feminino"}
_ALGORITHM_LABELS = {"xiaomi": "Xiaomi / Zepp Life", "science": "Científico"}


def _status_for(value: float, low: float | None, high: float | None) -> str:
    if low is not None and value < low:
        return "Abaixo"
    if high is not None and value > high:
        return "Acima"
    return "Normal"


def _range_text(low: float | None, high: float | None, unit: str, decimals: int = 1) -> str:
    if low is not None and high is not None:
        return f"{low:.{decimals}f}–{high:.{decimals}f}{unit}"
    if high is not None:
        return f"até {high:.{decimals}f}{unit}"
    if low is not None:
        return f"acima de {low:.{decimals}f}{unit}"
    return "—"


def _unit_text(value: float, decimals: int, unit: str) -> str:
    """Formata "valorUNIDADE" com espaço antes de unidades por extenso (kg, kcal, anos), sem espaço para símbolos (%)."""
    sep = "" if unit in ("", "%") else " "
    return f"{value:.{decimals}f}{sep}{unit}"


def report_path_for(measurement_id: int) -> Path:
    return REPORTS_DIR / f"{measurement_id}.pdf"


class RangeBar(Flowable):
    """Medidor horizontal abaixo/normal/acima no estilo "Análise Músculo-Gordura"
    de laudos de bioimpedância como o InBody: rótulos BAIXO/NORMAL/ALTO acima de
    uma trilha com as três zonas coloridas, uma barra preenchida do início até a
    posição do valor (como um gráfico de barras, não só um marcador), e números
    de escala nas fronteiras das zonas.
    """

    LABEL_H = 3.2 * mm
    SCALE_H = 3 * mm

    def __init__(self, value: float, low: float | None, high: float | None, width: float, height: float = 5 * mm):
        super().__init__()
        self.value = value
        self.low = low
        self.high = high
        self.width = width
        self.height = height

        # a escala de exibição precisa caber a(s) fronteira(s) conhecida(s) E o valor
        # medido, mesmo quando só há um lado da faixa (ex.: gordura visceral, sem piso)
        # ou quando o valor está bem fora da faixa — sem isso a janela calculada a
        # partir só das fronteiras colapsa perto de um dos lados e o valor "gruda" na borda.
        known_bounds = [b for b in (low, high) if b is not None]
        if len(known_bounds) == 2:
            scale = max(known_bounds) - min(known_bounds)
        elif known_bounds:
            scale = known_bounds[0]
        else:
            scale = abs(value)
        scale = max(scale, 0.1)

        floor = low if low is not None else 0.0
        ceiling = high
        candidates_low = [v for v in (floor, value) if v is not None]
        candidates_high = [v for v in (ceiling, value) if v is not None]
        # todas as métricas mostradas aqui (peso, massas, IMC, gordura visceral)
        # são fisicamente não-negativas — a janela nunca desce abaixo de zero
        self.min_display = max(0.0, min(candidates_low) - scale * 0.35)
        self.max_display = max(candidates_high) + scale * 0.35
        if self.max_display <= self.min_display:
            self.max_display = self.min_display + 1

    def _x_for(self, v: float) -> float:
        v = max(self.min_display, min(self.max_display, v))
        return (v - self.min_display) / (self.max_display - self.min_display) * self.width

    def wrap(self, available_width, available_height):
        return (self.width, self.height + self.LABEL_H + self.SCALE_H + 2)

    def draw(self) -> None:
        c = self.canv
        h = self.height
        bar_y = self.SCALE_H

        x_low = self._x_for(self.low) if self.low is not None else 0
        x_high = self._x_for(self.high) if self.high is not None else self.width

        # ------ rótulos BAIXO · NORMAL · ALTO acima da trilha (posicionados
        # sobre o centro de cada zona, como no InBody, não espaçados igualmente) ------
        c.setFont("Helvetica-Bold", 5.6)
        c.setFillColor(colors.HexColor("#6b7280"))
        label_y = bar_y + h + 1.4
        baixo_mid = x_low / 2
        normal_mid = (x_low + x_high) / 2
        alto_mid = (x_high + self.width) / 2
        c.drawCentredString(max(baixo_mid, 8), label_y, "BAIXO")
        c.drawCentredString(normal_mid, label_y, "NORMAL")
        c.drawCentredString(min(alto_mid, self.width - 6), label_y, "ALTO")

        # ------ trilha cinza clara única, sem zonas coloridas de fundo ------
        c.setStrokeColor(_TRACK_BORDER)
        c.setFillColor(_TRACK_GREY)
        c.roundRect(0, bar_y, self.width, h, h / 2, stroke=1, fill=1)

        # ------ barra preenchida do início até o valor (estilo gráfico de barras) ------
        status = _status_for(self.value, self.low, self.high)
        x_val = self._x_for(self.value)
        c.setFillColor(_STATUS_COLORS[status])
        c.roundRect(0, bar_y + h * 0.2, max(x_val, h * 0.3), h * 0.6, h * 0.3, stroke=0, fill=1)

        # ------ marcadores finos nas fronteiras baixo/normal/alto ------
        c.setStrokeColor(colors.HexColor("#9aa1a8"))
        c.setLineWidth(0.6)
        if self.low is not None:
            c.line(x_low, bar_y, x_low, bar_y + h)
        if self.high is not None:
            c.line(x_high, bar_y, x_high, bar_y + h)

        # ------ escala numérica com vários traços, não só as 2 fronteiras ------
        c.setFont("Helvetica", 5)
        c.setFillColor(colors.HexColor("#9aa1a8"))
        decimals = 0 if abs(self.max_display - self.min_display) >= 30 else 1
        tick_count = 7
        for i in range(tick_count):
            tick_v = self.min_display + (self.max_display - self.min_display) * i / (tick_count - 1)
            tick_x = self._x_for(tick_v)
            c.drawCentredString(tick_x, 0.4, f"{tick_v:.{decimals}f}")


def _weight_range_kg(height_cm: float) -> tuple[float, float]:
    """Faixa de peso "normal" derivada do IMC saudável (18,5–25) para a altura do cliente."""
    height_m = height_cm / 100
    return BMI_LOW * height_m**2, BMI_HIGH * height_m**2


def _fat_mass_range_kg(weight_kg: float, fat_pct_low: float | None, fat_pct_high: float | None) -> tuple[float | None, float | None]:
    """Converte a faixa de %gordura (já validada) para kg, usando o peso da própria medição."""
    low = fat_pct_low / 100 * weight_kg if fat_pct_low is not None else None
    high = fat_pct_high / 100 * weight_kg if fat_pct_high is not None else None
    return low, high


def _draw_top_bar(canvas, doc) -> None:
    """Tarja colorida no topo da página — o mesmo toque de marca dos laudos
    de bioimpedância de referência, com a paleta da MiScale em vez de copiar
    as cores de um fabricante de terceiros."""
    canvas.saveState()
    bar_h = 3.2 * mm
    stripe_colors = [_BRAND_TEAL, colors.HexColor("#00b8b4"), colors.HexColor("#8b5cf6"), colors.HexColor("#ff6b35")]
    stripe_w = A4[0] / len(stripe_colors)
    for i, stripe_color in enumerate(stripe_colors):
        canvas.setFillColor(stripe_color)
        canvas.rect(i * stripe_w, A4[1] - bar_h, stripe_w + 0.5, bar_h, stroke=0, fill=1)
    canvas.restoreState()


def generate_measurement_report(client: Client, measurement: dict) -> bytes:
    """Monta o PDF do resultado de uma medição e retorna os bytes prontos para salvar/servir."""
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle("TitleBrand", parent=styles["Title"], fontSize=18, spaceAfter=2)
    subtitle_style = ParagraphStyle("Subtitle", parent=styles["Normal"], fontSize=10, textColor=colors.grey)
    section_style = ParagraphStyle("Section", parent=styles["Heading2"], fontSize=13, spaceBefore=14, spaceAfter=6, textColor=_BRAND_TEAL)
    cell_style = ParagraphStyle("Cell", parent=styles["Normal"], fontSize=9.5)
    cell_bold_style = ParagraphStyle("CellBold", parent=cell_style, fontName="Helvetica-Bold")
    score_style = ParagraphStyle("Score", parent=styles["Normal"], fontSize=32, alignment=TA_CENTER, textColor=_BRAND_TEAL)
    footer_style = ParagraphStyle("Footer", parent=styles["Normal"], fontSize=8, textColor=colors.grey)

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4, topMargin=18 * mm, bottomMargin=16 * mm, leftMargin=18 * mm, rightMargin=18 * mm
    )
    story: list = []

    recorded_at = datetime.fromisoformat(measurement["recorded_at"])
    story.append(Paragraph("MiScale Analytics — Resultado da avaliação", title_style))
    story.append(Spacer(1, 4 * mm))

    # ======= Bloco de identificação (ID · Idade · Altura · Sexo · Data · Hora) =======
    algorithm = measurement.get("algorithm") or client.algorithm
    id_rows = [
        [Paragraph("<b>Nome</b>", cell_style), Paragraph(client.full_name, cell_style),
         Paragraph("<b>Idade</b>", cell_style), Paragraph(f"{client.age} anos", cell_style)],
        [Paragraph("<b>Altura</b>", cell_style), Paragraph(f"{client.height_cm:g} cm", cell_style),
         Paragraph("<b>Sexo</b>", cell_style), Paragraph(_SEX_LABELS.get(client.sex, client.sex), cell_style)],
        [Paragraph("<b>Data</b>", cell_style), Paragraph(recorded_at.strftime("%d/%m/%Y"), cell_style),
         Paragraph("<b>Hora</b>", cell_style), Paragraph(recorded_at.strftime("%H:%M"), cell_style)],
    ]
    id_table = Table(id_rows, colWidths=[22 * mm, 68 * mm, 22 * mm, 62 * mm])
    id_table.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.5, _TRACK_BORDER),
                ("BACKGROUND", (0, 0), (0, -1), _TRACK_GREY),
                ("BACKGROUND", (2, 0), (2, -1), _TRACK_GREY),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )
    story.append(id_table)
    story.append(Spacer(1, 6 * mm))

    # ======= Peso + Body Score em destaque =======
    weight = measurement["weight_kg"]
    body_score = measurement.get("body_score")
    header_data = [
        [Paragraph(f"{weight:.1f} kg", ParagraphStyle("Weight", parent=styles["Normal"], fontSize=22)), ""]
    ]
    if body_score is not None:
        header_data[0][1] = Paragraph(f"{body_score:.0f}<br/><font size=8>BODY SCORE</font>", score_style)
    header_table = Table(header_data, colWidths=[90 * mm, 70 * mm])
    header_table.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE")]))
    story.append(header_table)
    story.append(Spacer(1, 4 * mm))

    if measurement.get("bmi") is None:
        story.append(
            Paragraph(
                "Leitura sem impedância válida — só o peso foi registrado nesta medição.",
                ParagraphStyle("Warn", parent=styles["Normal"], textColor=colors.HexColor("#92450a")),
            )
        )
        story.append(Spacer(1, 10 * mm))
        story.append(Paragraph("As métricas de composição corporal são estimativas por bioimpedância elétrica, não uma medição clínica. Não use este relatório para decisões de saúde sem orientação profissional.", footer_style))
        story.append(Paragraph(f"Gerado em {datetime.now(timezone.utc).strftime('%d/%m/%Y %H:%M UTC')} — MiScale Analytics Desktop.", footer_style))
        doc.build(story, onFirstPage=_draw_top_bar, onLaterPages=_draw_top_bar)
        return buffer.getvalue()

    story.append(Paragraph(f"Algoritmo: {_ALGORITHM_LABELS.get(algorithm, algorithm)}", subtitle_style))

    body_input = BodyMetricsInput(
        weight_kg=weight, height_cm=client.height_cm, age=client.age, sex=client.sex, impedance_ohm=1.0
    )
    ranges = reference_ranges_for(body_input)

    fat_pct = measurement.get("fat_percentage")
    water_pct = measurement.get("water_percentage")
    protein_pct = measurement.get("protein_percentage")
    bone_mass = measurement.get("bone_mass_kg")

    # ======= Composição Corporal (por massa, kg) =======
    # Tabela "em escada", no mesmo espírito do InBody: cada componente soma ao
    # próximo até fechar dois subtotais — massa livre de gordura (ACT + proteína
    # + minerais) e, por fim, o peso total (massa livre de gordura + gordura).
    # Os subtotais aparecem uma única vez, na linha em que se completam.
    weight_low, weight_high = _weight_range_kg(client.height_cm)
    act_kg = weight * water_pct / 100 if water_pct is not None else None
    protein_kg = weight * protein_pct / 100 if protein_pct is not None else None
    fat_mass_kg = weight * fat_pct / 100 if fat_pct is not None else None
    ffm_kg = sum(v for v in (act_kg, protein_kg, bone_mass) if v is not None) or None

    comp_header = ["Componente", "Valores", "Massa livre de gordura", "Peso", "Faixa normal"]
    comp_rows = [comp_header]
    if act_kg is not None:
        comp_rows.append(["Água corporal total (ACT)", f"{act_kg:.1f} kg", "", "", "—"])
    if protein_kg is not None:
        comp_rows.append(["Proteínas", f"{protein_kg:.1f} kg", "", "", "—"])
    if bone_mass is not None:
        ffm_text = f"{ffm_kg:.1f} kg" if ffm_kg is not None else ""
        comp_rows.append(["Minerais (massa óssea)", f"{bone_mass:.2f} kg", ffm_text, "", "—"])
    if fat_mass_kg is not None:
        # o peso total só "fecha" aqui — é a única linha com uma faixa de
        # referência validada (as demais não têm faixa por componente)
        peso_text = f"{weight:.1f} kg" if ffm_kg is not None else ""
        range_text = _range_text(weight_low, weight_high, " kg") if ffm_kg is not None else "—"
        comp_rows.append(["Massa de gordura corporal", f"{fat_mass_kg:.1f} kg", "", peso_text, range_text])

    comp_table = Table(comp_rows, colWidths=[48 * mm, 24 * mm, 30 * mm, 22 * mm, 50 * mm])
    comp_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), _BRAND_TEAL),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTSIZE", (0, 0), (-1, -1), 8.5),
                ("ALIGN", (1, 0), (3, -1), "CENTER"),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("GRID", (0, 0), (-1, -1), 0.5, _TRACK_BORDER),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f6f7f5")]),
            ]
        )
    )
    story.append(KeepTogether([Paragraph("Composição Corporal", section_style), comp_table]))

    # ======= Análise Músculo-Gordura (barras: Peso · Massa muscular · Massa de gordura) =======
    muscle_range = ranges["muscle_mass_kg"]
    fat_range_pct = ranges["fat_percentage"]
    fat_low_kg, fat_high_kg = _fat_mass_range_kg(weight, fat_range_pct.low, fat_range_pct.high)

    bar_rows = [["Métrica", "Valor", "Faixa abaixo · normal · acima", "Status"]]
    bar_specs = [("Peso", weight, weight_low, weight_high, " kg", 1)]
    if measurement.get("muscle_mass_kg") is not None:
        bar_specs.append(("Massa muscular (MME)", measurement["muscle_mass_kg"], muscle_range.low, muscle_range.high, " kg", 1))
    if fat_pct is not None:
        bar_specs.append(("Massa de gordura corporal", weight * fat_pct / 100, fat_low_kg, fat_high_kg, " kg", 1))

    for label, value, low, high, unit, decimals in bar_specs:
        status = _status_for(value, low, high)
        bar_rows.append(
            [
                Paragraph(label, cell_style),
                Paragraph(f"{value:.{decimals}f}{unit}", cell_bold_style),
                RangeBar(value, low, high, width=58 * mm),
                Paragraph(status, ParagraphStyle("Status", parent=cell_bold_style, textColor=_STATUS_COLORS[status])),
            ]
        )
    _bar_style = TableStyle(
        [
            ("BACKGROUND", (0, 0), (-1, 0), _BRAND_TEAL),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTSIZE", (0, 0), (-1, -1), 9.5),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("GRID", (0, 0), (-1, -1), 0.5, _TRACK_BORDER),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f6f7f5")]),
        ]
    )
    bar_table = Table(bar_rows, colWidths=[42 * mm, 24 * mm, 62 * mm, 26 * mm])
    bar_table.setStyle(_bar_style)
    story.append(KeepTogether([Paragraph("Análise Músculo-Gordura", section_style), bar_table]))

    # ======= Diagnóstico da Obesidade (barras: IMC · Gordura % · Gordura visceral) =======
    obesity_rows = [["Métrica", "Valor", "Faixa abaixo · normal · acima", "Status"]]
    obesity_specs = []
    if measurement.get("bmi") is not None:
        r = ranges["bmi"]
        obesity_specs.append(("IMC", measurement["bmi"], r.low, r.high, "", 1))
    if fat_pct is not None:
        obesity_specs.append(("Gordura corporal (PGC)", fat_pct, fat_range_pct.low, fat_range_pct.high, "%", 1))
    if measurement.get("visceral_fat") is not None:
        r = ranges["visceral_fat"]
        obesity_specs.append(("Gordura visceral", measurement["visceral_fat"], r.low, r.high, "", 1))

    for label, value, low, high, unit, decimals in obesity_specs:
        status = _status_for(value, low, high)
        obesity_rows.append(
            [
                Paragraph(label, cell_style),
                Paragraph(f"{value:.{decimals}f}{unit}", cell_bold_style),
                RangeBar(value, low, high, width=58 * mm),
                Paragraph(status, ParagraphStyle("Status2", parent=cell_bold_style, textColor=_STATUS_COLORS[status])),
            ]
        )
    obesity_table = Table(obesity_rows, colWidths=[42 * mm, 24 * mm, 62 * mm, 26 * mm])
    obesity_table.setStyle(_bar_style)
    story.append(KeepTogether([Paragraph("Diagnóstico da Obesidade", section_style), obesity_table]))

    # ======= Controle de Peso (quanto falta pra chegar ao meio da faixa normal) =======
    # Só entra quando dá pra apoiar em faixas já validadas (peso e %gordura) — o
    # "controle muscular" é a diferença entre os dois por conservação de massa
    # (Δpeso = Δgordura + Δmagra), não um terceiro limiar inventado.
    if fat_mass_kg is not None and fat_range_pct.low is not None and fat_range_pct.high is not None:
        target_weight = (weight_low + weight_high) / 2
        controle_peso = target_weight - weight
        target_fat_kg = (fat_range_pct.low + fat_range_pct.high) / 2 / 100 * target_weight
        controle_gordura = target_fat_kg - fat_mass_kg
        controle_muscular = controle_peso - controle_gordura

        def _signed(v: float) -> str:
            return f"{'+' if v >= 0 else ''}{v:.1f} kg"

        control_rows = [
            ["Controle de peso", _signed(controle_peso)],
            ["Controle de gordura", _signed(controle_gordura)],
            ["Controle muscular", _signed(controle_muscular)],
        ]
        control_table = Table(control_rows, colWidths=[75 * mm, 99 * mm])
        control_table.setStyle(
            TableStyle(
                [
                    ("FONTSIZE", (0, 0), (-1, -1), 9.5),
                    ("FONTNAME", (1, 0), (1, -1), "Helvetica-Bold"),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                    ("TOPPADDING", (0, 0), (-1, -1), 6),
                    ("GRID", (0, 0), (-1, -1), 0.5, _TRACK_BORDER),
                    ("ROWBACKGROUNDS", (0, 0), (-1, -1), [colors.white, colors.HexColor("#f6f7f5")]),
                ]
            )
        )
        story.append(
            KeepTogether(
                [
                    Paragraph("Controle de Peso", section_style),
                    Paragraph(
                        f"Estimativa pra chegar ao meio da faixa normal ({target_weight:.1f} kg) — "
                        "não é uma meta clínica, só uma referência.",
                        ParagraphStyle("ControlHint", parent=subtitle_style, spaceAfter=4),
                    ),
                    control_table,
                ]
            )
        )

    # ======= Demais métricas (sem faixa validada — número simples) =======
    extra_rows = [["Métrica", "Valor"]]
    for metric_id in ("water_percentage", "bmr_kcal", "metabolic_age", "protein_percentage"):
        value = measurement.get(metric_id)
        if value is None:
            continue
        label, unit, decimals = _METRIC_INFO[metric_id]
        extra_rows.append([label, _unit_text(value, decimals, unit)])
    if len(extra_rows) > 1:
        extra_table = Table(extra_rows, colWidths=[75 * mm, 99 * mm])
        extra_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), _BRAND_TEAL),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("FONTSIZE", (0, 0), (-1, -1), 9.5),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                    ("TOPPADDING", (0, 0), (-1, -1), 6),
                    ("GRID", (0, 0), (-1, -1), 0.5, _TRACK_BORDER),
                    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f6f7f5")]),
                ]
            )
        )
        story.append(KeepTogether([Paragraph("Outras métricas", section_style), extra_table]))

    story.append(Spacer(1, 10 * mm))
    story.append(
        Paragraph(
            "As métricas de composição corporal são estimativas por bioimpedância elétrica, não uma medição "
            "clínica. Não use este relatório para decisões de saúde sem orientação profissional.",
            footer_style,
        )
    )
    story.append(
        Paragraph(f"Gerado em {datetime.now(timezone.utc).strftime('%d/%m/%Y %H:%M UTC')} — MiScale Analytics Desktop.", footer_style)
    )

    doc.build(story, onFirstPage=_draw_top_bar, onLaterPages=_draw_top_bar)
    return buffer.getvalue()


def generate_and_save_report(client: Client, measurement: dict) -> Path:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    path = report_path_for(measurement["id"])
    path.write_bytes(generate_measurement_report(client, measurement))
    return path
