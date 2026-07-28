#!/usr/bin/env python3
"""Invoca um modelo Groq com o contexto preparado e salva a resposta JSON."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Protocol

from dotenv import dotenv_values


class LlmInvocationError(RuntimeError):
    """Indica que o contrato de invocação do LLM não foi atendido."""


class StructuredLlm(Protocol):
    def invoke(self, messages: list[tuple[str, str]]) -> dict[str, Any]:
        """Executa uma chamada e devolve a resposta estruturada."""


SCRIPT_ENV_PATH = Path(__file__).resolve().parent / ".env"


def _require_object(value: Any, location: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise LlmInvocationError(f"{location} deve ser um objeto JSON.")
    return value


def load_json_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise LlmInvocationError(f"Não foi possível ler {path}: {error}") from error
    return _require_object(value, str(path))


def load_groq_api_key(env_path: Path) -> str:
    if not env_path.is_file():
        raise LlmInvocationError(
            f"O arquivo de configuração do Groq não existe: {env_path}"
        )
    try:
        values = dotenv_values(
            dotenv_path=env_path,
            encoding="utf-8",
            interpolate=False,
        )
    except OSError as error:
        raise LlmInvocationError(
            f"Não foi possível ler o arquivo de configuração {env_path}: {error}"
        ) from error
    api_key = values.get("GROQ_API_KEY")
    if not isinstance(api_key, str) or not api_key.strip():
        raise LlmInvocationError(
            f"GROQ_API_KEY não está definida no arquivo {env_path}."
        )
    return api_key


def build_messages(
    prepared_context: dict[str, Any], prompt_contract: dict[str, Any]
) -> list[tuple[str, str]]:
    context = _require_object(prepared_context, "Contexto preparado")
    prompt = _require_object(prompt_contract, "Contrato do prompt")
    validation = _require_object(context.get("validation"), "validation")
    if validation.get("ready_for_llm") is not True:
        issues = validation.get("blocking_issues")
        raise LlmInvocationError(
            f"O contexto não está pronto para o LLM. Bloqueios: {issues!r}"
        )

    traceability = _require_object(context.get("traceability"), "traceability")
    context_prompt_version = traceability.get("prompt_version")
    contract_prompt_version = prompt.get("prompt_version")
    if context_prompt_version != contract_prompt_version:
        raise LlmInvocationError(
            "A prompt_version do contexto não corresponde à versão do contrato "
            f"({context_prompt_version!r} != {contract_prompt_version!r})."
        )

    system_prompt = prompt.get("system_prompt")
    user_template = prompt.get("user_prompt_template")
    if not isinstance(system_prompt, str) or not system_prompt.strip():
        raise LlmInvocationError("system_prompt deve ser uma string não vazia.")
    if not isinstance(user_template, str) or not user_template.strip():
        raise LlmInvocationError("user_prompt_template deve ser uma string não vazia.")

    placeholder = "{{llm_context_json}}"
    if user_template.count(placeholder) != 1:
        raise LlmInvocationError(
            "user_prompt_template deve conter exatamente uma ocorrência de "
            "{{llm_context_json}}."
        )
    llm_context = _require_object(context.get("llm_context"), "llm_context")
    context_json = json.dumps(llm_context, ensure_ascii=False, indent=2)
    user_prompt = user_template.replace(placeholder, context_json)
    return [("system", system_prompt), ("human", user_prompt)]


def response_schema(prompt_contract: dict[str, Any]) -> dict[str, Any]:
    response_contract = _require_object(
        prompt_contract.get("response_schema"), "response_schema"
    )
    name = response_contract.get("name")
    strict = response_contract.get("strict")
    schema = _require_object(response_contract.get("schema"), "response_schema.schema")
    if not isinstance(name, str) or not name.strip():
        raise LlmInvocationError("response_schema.name deve ser uma string não vazia.")
    if strict is not True:
        raise LlmInvocationError(
            "response_schema.strict deve ser true para esta invocação."
        )
    return {"title": name, **schema}


def create_groq_structured_llm(
    *,
    model: str,
    timeout_seconds: float,
    prompt_contract: dict[str, Any],
    api_key: str,
) -> StructuredLlm:
    try:
        from langchain_groq import ChatGroq
    except ImportError as error:
        raise LlmInvocationError(
            "langchain-groq não está instalado. Instale agent-requirements.txt."
        ) from error

    llm = ChatGroq(
        model=model,
        temperature=0,
        timeout=timeout_seconds,
        max_retries=0,
        api_key=api_key,
    )
    return llm.with_structured_output(
        response_schema(prompt_contract),
        method="json_schema",
        strict=True,
    )


def invoke_structured_llm(
    llm: StructuredLlm, messages: list[tuple[str, str]]
) -> dict[str, Any]:
    result = llm.invoke(messages)
    return _require_object(result, "Resposta estruturada do LLM")


def write_json_exclusive(path: Path, value: dict[str, Any]) -> None:
    try:
        with path.open("x", encoding="utf-8") as output:
            json.dump(value, output, ensure_ascii=False, indent=2)
            output.write("\n")
    except FileExistsError as error:
        raise LlmInvocationError(
            f"O arquivo de saída já existe e não será sobrescrito: {path}"
        ) from error


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Invoca um modelo Groq para produzir a narrativa estruturada."
    )
    parser.add_argument("--context", required=True, type=Path)
    parser.add_argument("--prompt-contract", required=True, type=Path)
    parser.add_argument("--model", required=True)
    parser.add_argument("--timeout-seconds", required=True, type=float)
    parser.add_argument("--output", required=True, type=Path)
    return parser


def main() -> None:
    parser = build_argument_parser()
    args = parser.parse_args()
    if args.output.exists():
        parser.error(
            f"O arquivo de saída já existe e não será sobrescrito: {args.output}"
        )
    if args.timeout_seconds <= 0:
        parser.error("--timeout-seconds deve ser maior que zero.")
    try:
        context = load_json_object(args.context)
        prompt = load_json_object(args.prompt_contract)
        messages = build_messages(context, prompt)
        api_key = load_groq_api_key(SCRIPT_ENV_PATH)
        llm = create_groq_structured_llm(
            model=args.model,
            timeout_seconds=args.timeout_seconds,
            prompt_contract=prompt,
            api_key=api_key,
        )
        result = invoke_structured_llm(llm, messages)
        write_json_exclusive(args.output, result)
    except LlmInvocationError as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
