import csv
import io
from urllib.parse import quote
from pydantic import BaseModel

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
    # 1. 全局参数严格校验
    # document_id 必须非空且不含首尾空白字符
    if not value.document_id or value.document_id != value.document_id.strip():
        raise ValueError("document_id must not be empty and must not contain leading/trailing whitespace")
    # primary_key 必须非空
    if not value.primary_key:
        raise ValueError("primary_key cannot be empty")

    # 2. 解码，自动处理 UTF-8 BOM 头
    try:
        text = value.content.decode('utf-8-sig')
    except UnicodeDecodeError:
        raise ValueError("Invalid encoding, must be UTF-8")

    # 3. 使用 strict=True 的 CSV 解析器
    reader = csv.reader(io.StringIO(text), strict=True)

    # 读取表头
    try:
        header = next(reader)
    except StopIteration:
        raise ValueError("Empty document")

    # 校验表头：非空、非纯空白、唯一
    if not header or any(not col.strip() for col in header):
        raise ValueError("Header fields must not be empty or pure whitespace")
    if len(header) != len(set(header)):
        raise ValueError("Header fields must be unique")

    # 校验主键是否在表头中（必须完全匹配，包括空格）
    if value.primary_key not in header:
        raise ValueError(f"Primary key '{value.primary_key}' not in header")
    pk_index = header.index(value.primary_key)

    rows = []
    seen_pks = set()

    # 4. 逐行解析数据
    for row_num, row in enumerate(reader, start=2):
        # 忽略完全空白的物理行（空字符串或纯空格）
        if not row or all(not cell.strip() for cell in row):
            continue

        # 列数必须等于表头宽度
        if len(row) != len(header):
            raise ValueError(f"Row {row_num} column count mismatch")

        pk_val = row[pk_index]

        # 主键值不能是空字符串或纯空白
        if not pk_val or not pk_val.strip():
            raise ValueError(f"Row {row_num} primary key is empty or pure whitespace")
        
        # 主键值在同一文档内唯一
        if pk_val in seen_pks:
            raise ValueError(f"Duplicate primary key: {pk_val}")
        seen_pks.add(pk_val)

        # 校验生成的 source_id 不超过 256 个字符
        source_id = csv_row_source_id(value.document_id, pk_val)
        if len(source_id) > 256:
            raise ValueError(f"Generated source_id exceeds 256 characters")

        # 组装返回对象（不做任何 trim、类型转换）
        rows.append(CSVRowInput(
            document_id=value.document_id,
            primary_key=value.primary_key,
            primary_key_value=pk_val,
            columns=tuple(header),
            values=tuple(row)
        ))

    return tuple(rows)

def csv_row_source_id(document_id: str, primary_key_value: str) -> str:
    # 分别按 urllib.parse.quote 进行百分号编码
    doc_encoded = quote(document_id, safe='')
    pk_encoded = quote(primary_key_value, safe='')
    return f"csv:{doc_encoded}:{pk_encoded}"

CSV_ROW_SOURCE_DEFINITION = SourceDefinition(
    name="csv-row",
    version=1,
    input_class=CSVRowInput,
    source_class=CSVRowSource
)