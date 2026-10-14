"""Structurally valid documents containing explicitly synthetic source content."""
import io

from openpyxl import Workbook
from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject

from travel_claim.sources import WORKBOOK_TABS


def pdf_bytes(text='SYNTHETIC source document only'):
    writer = PdfWriter()
    page = writer.add_blank_page(width=600, height=800)
    font = DictionaryObject({NameObject('/Type'): NameObject('/Font'), NameObject('/Subtype'): NameObject('/Type1'), NameObject('/BaseFont'): NameObject('/Helvetica')})
    page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'): DictionaryObject({NameObject('/F1'): font})})
    stream = DecodedStreamObject()
    stream.set_data(f'BT /F1 12 Tf 20 750 Td ({text}) Tj ET'.encode())
    page[NameObject('/Contents')] = writer._add_object(stream)
    buffer = io.BytesIO(); writer.write(buffer)
    return buffer.getvalue()


def xlsx_bytes():
    workbook = Workbook(); workbook.remove(workbook.active)
    for name in sorted(WORKBOOK_TABS):
        workbook.create_sheet(name).append(['SYNTHETIC source document only'])
    buffer = io.BytesIO(); workbook.save(buffer); workbook.close()
    return buffer.getvalue()
