"""DynamoDB / S3 / SNS access. boto3 comes with the Lambda runtime; imports are lazy so the
model and tests run without it.

Single table: pk / sk (both strings)
  RISK#<city>  /  <ISO timestamp>            one record per ingest run (history doubles as back-test log)
  ADV#<city>   /  <risk timestamp>#<lang>    cached agent advisory for that risk record
"""
import json
from decimal import Decimal

TTL_SECONDS = 14 * 24 * 3600


def to_ddb(obj):
    """DynamoDB rejects Python floats; round-trip through Decimal."""
    return json.loads(json.dumps(obj), parse_float=Decimal)


def from_ddb(obj):
    if isinstance(obj, list):
        return [from_ddb(x) for x in obj]
    if isinstance(obj, dict):
        return {k: from_ddb(v) for k, v in obj.items()}
    if isinstance(obj, Decimal):
        return int(obj) if obj == obj.to_integral_value() else float(obj)
    return obj


def _table(name):
    import boto3
    return boto3.resource("dynamodb").Table(name)


def put_risk(table_name, city_key, ts_iso, record, now_epoch):
    item = {"pk": f"RISK#{city_key}", "sk": ts_iso, "ttl": int(now_epoch) + TTL_SECONDS, **record}
    _table(table_name).put_item(Item=to_ddb(item))


def latest_risk(table_name, city_key):
    from boto3.dynamodb.conditions import Key
    resp = _table(table_name).query(
        KeyConditionExpression=Key("pk").eq(f"RISK#{city_key}"), ScanIndexForward=False, Limit=1)
    items = resp.get("Items", [])
    return from_ddb(items[0]) if items else None


def get_advisory(table_name, city_key, risk_ts, lang):
    resp = _table(table_name).get_item(Key={"pk": f"ADV#{city_key}", "sk": f"{risk_ts}#{lang}"})
    item = resp.get("Item")
    return from_ddb(item) if item else None


def put_advisory(table_name, city_key, risk_ts, lang, advisory, now_epoch):
    _table(table_name).put_item(Item=to_ddb({
        "pk": f"ADV#{city_key}", "sk": f"{risk_ts}#{lang}", "ttl": int(now_epoch) + TTL_SECONDS, **advisory}))


def put_raw(bucket, key, body):
    import boto3
    boto3.client("s3").put_object(Bucket=bucket, Key=key, Body=body.encode("utf-8"))


def publish_alert(topic_arn, subject, message):
    import boto3
    boto3.client("sns").publish(TopicArn=topic_arn, Subject=subject[:100], Message=message)
