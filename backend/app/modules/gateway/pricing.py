from decimal import ROUND_HALF_UP, Decimal

from app.db.models import ProviderModel


def priced(model: ProviderModel) -> bool:
    if model.currency != "CNY":
        return False
    if model.tiered_pricing:
        return bool(model.input_price_tiers and model.output_price_tiers)
    return model.input_price is not None and model.output_price is not None


def tier_price(tiers: list[dict], tokens: int) -> Decimal:
    for tier in tiers:
        maximum = tier["up_to_tokens"]
        if maximum is None or tokens <= maximum:
            return Decimal(str(tier["price"]))
    raise ValueError("model_price_missing")


def cents(model: ProviderModel, input_tokens: int, output_tokens: int) -> int:
    if not priced(model):
        raise ValueError("model_price_missing")
    if model.tiered_pricing:
        input_price = tier_price(model.input_price_tiers, input_tokens)
        output_price = tier_price(model.output_price_tiers, output_tokens)
    else:
        input_price, output_price = model.input_price, model.output_price
    total = (Decimal(input_tokens) * input_price
             + Decimal(output_tokens) * output_price) / (1000 * model.price_unit_k)
    return int((total * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
