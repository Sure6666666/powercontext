import csv
import io
import json
from urllib.parse import quote
from pydantic import BaseModel, model_validator

from .models import Source, SourceMaterialization
from powercontext.limits import MAX_SOURCE_ID_LENGTH
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
    # 补全业务字段
    source_id: str
    document_id: str
    primary_key: str
    primary_key_value: str
    columns: tuple[str, ...]
    values: tuple[str, ...]
    
    # 强制使用官方枚举
    materialization: SourceMaterialization = SourceMaterialization.CAPTURED

    # 关键修正：使用 model_validator 强行让 name 等于 source_id
    @model_validator(mode="after")
    def sync_name_with_source_id(self):
        self.name = self.source_id
        return self

    # 实现赛题 2.4 要求的 TextEvidence 投影
    def to_text_evidence(self) -> dict:
        # 按照表头顺序构造字典
        row_dict = dict(zip(self.columns, self.values))
        
        # 紧凑型 JSON，保留中文
        content_json = json.dumps(row_dict, ensure_ascii=False, separators=(',', ':'))
        
        # 严格包含这 5 个键
        metadata = {
            "document_id": self.document_id,
            "primary_key": self.primary_key,
            "primary_key_value": self.primary_key_value,
            "columns": list(self.columns),
            "row": row_dict
        }
        
        return {
            "source_type": "csv-row",
            "source_id": self.source_id,
            "content": content_json,
            "metadata": metadata
        }

def parse_csv_document(value: CSVDocumentInput) -> tuple[CSVRowInput, ...]:
    # 1. 严格校验 document_id 和 primary_key
    if not value.document_id or value.document_id != value.document_id.strip():
        raise ValueError("document_id must not be empty and must not contain leading/trailing whitespace")
    if not value.primary_key:
        raise ValueError("primary_key cannot be empty")

    # 2. 解码，处理 BOM
    try:
        text = value.content.decode('utf-8-sig')
    except UnicodeDecodeError:
        raise ValueError("Invalid encoding, must be UTF-8")

    reader = csv.reader(io.StringIO(text), strict=True)
    
    # 3. 读取表头并校验
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

    # 4. 逐行解析
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

        source_id = csv_row_source_id(value.document_id, pk_val)
        if len(source_id) > MAX_SOURCE_ID_LENGTH:
            raise ValueError(f"Generated source_id exceeds {MAX_SOURCE_ID_LENGTH} characters")

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