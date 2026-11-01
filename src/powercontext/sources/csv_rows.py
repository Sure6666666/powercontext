import csv
import io
import json
from urllib.parse import quote
from pydantic import BaseModel

from .models import Source, SourceMaterialization
from powercontext.limits import MAX_SOURCE_ID_LENGTH
from .definitions import SourceDefinition
from powercontext.sources.projections import TEXT_EVIDENCE_PROJECTION_KEY

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
    # 显式声明所有字段，不搞自动推导，防止框架实例化报错
    source_id: str
    document_id: str
    primary_key: str
    primary_key_value: str
    columns: tuple[str, ...]
    values: tuple[str, ...]
    materialization: SourceMaterialization = SourceMaterialization.CAPTURED

    def projection(self, key: str) -> dict:
        if key == TEXT_EVIDENCE_PROJECTION_KEY:
            # 构造原表头顺序的字典
            row_dict = dict(zip(self.columns, self.values))
            content_json = json.dumps(row_dict, ensure_ascii=False, separators=(',', ':'))
            return {
                "source_type": "csv-row",
                "source_id": self.source_id,
                "content": content_json,
                "metadata": {
                    "document_id": self.document_id,
                    "primary_key": self.primary_key,
                    "primary_key_value": self.primary_key_value,
                    "columns": list(self.columns),
                    "row": row_dict
                }
            }
        raise ValueError(f"Unknown projection key: {key}")

def parse_csv_document(value: CSVDocumentInput) -> tuple[CSVRowInput, ...]:
    if not value.document_id or value.document_id != value.document_id.strip():
        raise ValueError("document_id must not be empty and must not contain leading/trailing whitespace")
    if not value.primary_key:
        raise ValueError("primary_key cannot be empty")

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
        raise ValueError("Header fields must not be empty or pure whitespace")
    if len(header) != len(set(header)):
        raise ValueError("Header fields must be unique")

    if value.primary_key not in header:
        raise ValueError(f"Primary key '{value.primary_key}' not in header")
    pk_index = header.index(value.primary_key)

    rows = []
    seen_pks = set()

    for row_num, row in enumerate(reader, start=2):
        if not row or all(not cell.strip() for cell in row):
            continue

        if len(row) != len(header):
            raise ValueError(f"Row {row_num} column count mismatch")

        pk_val = row[pk_index]
        
        if not pk_val or not pk_val.strip():
            raise ValueError(f"Row {row_num} primary key is empty or pure whitespace")
        if pk_val in seen_pks:
            raise ValueError(f"Duplicate primary key: {pk_val}")
        seen_pks.add(pk_val)

        # 提前调用校验，如果超长或带空格会在此时报错
        csv_row_source_id(value.document_id, pk_val)

        rows.append(CSVRowInput(
            document_id=value.document_id,
            primary_key=value.primary_key,
            primary_key_value=pk_val,
            columns=tuple(header),
            values=tuple(row)
        ))

    return tuple(rows)

def csv_row_source_id(document_id: str, primary_key_value: str) -> str:
    if document_id != document_id.strip():
         raise ValueError("document_id contains leading/trailing whitespace")
    
    doc_encoded = quote(document_id, safe='')
    pk_encoded = quote(primary_key_value, safe='')
    sid = f"csv:{doc_encoded}:{pk_encoded}"
    
    if len(sid) > MAX_SOURCE_ID_LENGTH:
        raise ValueError(f"Generated source_id exceeds {MAX_SOURCE_ID_LENGTH} characters")
        
    return sid

CSV_ROW_SOURCE_DEFINITION = SourceDefinition(
    name="csv-row",
    version=1,
    input_class=CSVRowInput,
    source_class=CSVRowSource
)
