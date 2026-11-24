from io import BytesIO
from docx import Document
from docx.shared import Pt


def variant_document(variant, full=False):
    doc = Document()
    style = doc.styles['Normal']
    style.font.name = 'Times New Roman'
    style.font.size = Pt(12)
    meta = variant.metadata
    if full:
        doc.add_paragraph('Министерство науки и высшего образования Российской Федерации', style='Title')
        doc.add_paragraph('ФГБОУ ВО «Кубанский государственный университет»')
        doc.add_paragraph('Факультет математики и компьютерных наук')
        doc.add_heading('ОТЧЁТ ПО ПРАКТИКЕ', 0)
        doc.add_paragraph(meta['practice_title'])
        doc.add_paragraph(f"Направление: {meta['program']}\nГруппа: {meta['cohort']}\nСтудент: {meta['student']}\nРуководитель: {meta['supervisor']}\nКафедра: {meta['department']}\nСроки: {meta['start_date']} — {meta['end_date']}")
        doc.add_paragraph('Краснодар')
        doc.add_page_break()
        doc.add_heading('Лист инструктажа', 0)
        doc.add_paragraph('Инструктаж по охране труда, технике безопасности, пожарной безопасности и правилам внутреннего распорядка.')
        for text in ['Дата инструктажа: __________________', f"Инструктаж прошёл: {meta['student']} / ______________", 'Инструктаж провёл: __________________ / ______________']:
            doc.add_paragraph(text)
        doc.add_page_break()
        doc.add_heading('Оценочный лист', 0)
        doc.add_paragraph(f"Студент: {meta['student']}\nРуководитель: {meta['supervisor']}")
        doc.add_heading('Компетенции по направлению подготовки', 1)
        doc.add_paragraph(meta['competencies'])
        table = doc.add_table(rows=1, cols=2)
        table.style = 'Table Grid'
        table.rows[0].cells[0].text = 'Критерий'
        table.rows[0].cells[1].text = 'Оценка / комментарий'
        for criterion in ['Выполнение индивидуального задания', 'Качество отчёта', 'Защита отчёта', 'Итоговая оценка']:
            table.add_row().cells[0].text = criterion
        doc.add_paragraph('Подпись руководителя: ______________  Дата: ______________')
        doc.add_page_break()
    doc.add_heading(f"{meta.get('heading', 'Индивидуальное задание')} · вариант {variant.pk:04d}", 0)
    doc.add_paragraph(f"{meta['student']} · {meta['cohort']}\n{meta['program']}\n{meta['practice_title']}\nРуководитель: {meta['supervisor']}\nСроки: {meta['start_date']} — {meta['end_date']}")
    doc.add_paragraph(meta.get('introduction', ''))
    for index, item in enumerate(variant.items.all(), 1):
        doc.add_heading(f'{index}. {item.topic_name}', 1)
        doc.add_paragraph(item.text)
    doc.add_paragraph(meta.get('footer', ''))
    doc.add_paragraph(f"Вариант закреплён на {meta['academic_year']}/{meta['academic_year'] + 1} учебный год.")
    stream = BytesIO()
    doc.save(stream)
    stream.seek(0)
    return stream
