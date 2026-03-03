import json
import os
from jsonschema import Draft202012Validator
from jsonschema.validators import validator_for
from jsonschema import RefResolver  

def load_schema(schema_path: str) -> dict:
    with open(schema_path, "r", encoding="utf-8") as f:
        return json.load(f)

def validate_json(data: dict, schema_path: str) -> list[str]:
    schema = load_schema(schema_path)

    base_dir = os.path.dirname(os.path.abspath(schema_path))
    base_uri = f"file:///{base_dir.replace(os.sep, '/')}/"

    resolver = RefResolver(base_uri=base_uri, referrer=schema)

    Validator = validator_for(schema)
    validator = Validator(schema, resolver=resolver)

    errors = sorted(validator.iter_errors(data), key=lambda e: list(e.path))

    messages = []
    for err in errors:
        loc = ".".join([str(x) for x in err.path]) if err.path else "(root)"
        messages.append(f"{loc}: {err.message}")
    return messages