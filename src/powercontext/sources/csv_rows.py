import csv
import io
from urllib.parse import quote
from pydantic import BaseModel

# 注意：如果下面这两行出现红色波浪线，说明路径不对
# 请在左侧文件树里找一下 models.py 和 definitions.py 在哪里
from .models import Source
from .definitions import SourceDefinition

class CSVDocumentInput(BaseModel):
    document_id: str
    primary_key: str
    content: bytes

class CSVRowInput(BaseModel):
    document_id: str
    primary_key: str
    primary_key_value: str
    columns: tuple[str, ...]
    values: tuple[str, ...]

class CSVRowSource(Source):
    source_id: str
    document_id: str
    primary_key: str
    primary_key_value: str
    columns: tuple[str, ...]
    values: tuple[str, ...]

def parse_csv_document(value: CSVDocumentInput) -> tuple[CSVRowInput, ...]:
    try:
        text = value.content.decode('utf-8-sig')
    except UnicodeDecodeError:
        raise ValueError("Invalid encoding, must be UTF-8")

    reader = csv.reader(io.StringIO(text), strict=True)
    
    try:
        header = next(reader)
    except StopIteration:
        raise ValueError("Empty document")

    if not header or any(not col.strip() for col in header):
        raise ValueError("Header fields must not be empty")
    if len(header) != len(set(header)):
        raise ValueError("Header fields must be unique")

    if value.primary_key not in header:
        raise ValueError(f"Primary key '{value.primary_key}' not in header")
    pk_index = header.index(value.primary_key)

    rows = []
    seen_pks = set()

    for row_num, row in enumerate(reader, start=2):
        if not row or all(cell == '' for cell in row):
            continue
        if len(row) != len(header):
            raise ValueError(f"Row {row_num} column count mismatch")

        pk_val = row[pk_index]
        if not pk_val.strip():
            raise ValueError(f"Row {row_num} primary key is empty")
        if pk_val in seen_pks:
            raise ValueError(f"Duplicate primary key: {pk_val}")
        seen_pks.add(pk_val)

        rows.append(CSVRowInput(
            document_id=value.document_id,
            primary_key=value.primary_key,
            primary_key_value=pk_val,
            columns=tuple(header),
            values=tuple(row)
        ))

    return tuple(rows)

def csv_row_source_id(document_id: str, primary_key_value: str) -> str:
    doc_encoded = quote(document_id, safe='')
    pk_encoded = quote(primary_key_value, safe='')
    return f"csv:{doc_encoded}:{pk_encoded}"

CSV_ROW_SOURCE_DEFINITION = SourceDefinition(
    name="csv-row",
    version=1,
    input_class=CSVRowInput,
    source_class=CSVRowSource
)