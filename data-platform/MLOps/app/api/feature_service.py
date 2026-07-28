from typing import Any

from sqlalchemy import Engine, text


class CustomerNotFoundError(LookupError):
    pass


ABT_QUERY = text(
    """
    SELECT *
    FROM application_abt
    WHERE sk_id_curr = :customer_id
    """
)


class CustomerFeatureService:
    """Busca na ABT as mesmas features utilizadas durante o treinamento."""

    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def build(self, customer_id: int) -> dict[str, Any]:
        with self.engine.connect() as connection:
            customer = connection.execute(
                ABT_QUERY, {"customer_id": customer_id}
            ).mappings().first()

        if customer is None:
            raise CustomerNotFoundError(
                f"Cliente {customer_id} não encontrado em application_abt."
            )

        features = {
            column: self._python_value(value)
            for column, value in customer.items()
            if column not in {"sk_id_curr", "target"}
        }
        return features

    @staticmethod
    def _python_value(value: Any) -> Any:
        return value.item() if hasattr(value, "item") else value
