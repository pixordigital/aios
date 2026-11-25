"""SDR voice-answer prompt: modern WEBAI 01, 1 dial, 0 visits, respostas HIGH_VALUE."""


SDR_VOICE_PROMPT = """# SDR Voice Answer — modern WEBAI 01, 1 dial, 0 visits
Responda em 1-2 frases. 1 dial por resposta, 0 visitas.
Respostas no estilo HIGH_VALUE: diretas, sem enrolação, próximo passo por mensagem.
Sem presença física, só WhatsApp (Voice Answer via Evolution).
"""


def _duplicated_number_risks(profile):
    seen, out = set(), []
    for n in (profile or {}).get("duplicated_numbers", []) or []:
        if n and n not in seen:
            seen.add(n)
            out.append(f"numero {n} duplicado")
    return out


def sdr_prompt(profile=None):
    """Prompt params for the SDR voice answer.

    Returns dict(profile, vora=default, subject, timezones, follow_ups, risks).
    """
    profile = profile or {}
    return {
        "profile": profile,
        "vora": "default",
        "subject": "Prospecao WhatsApp Business — Voice Answer",
        "timezones": ["America/Sao_Paulo"],
        "dials": 1,
        "visits": 0,
        "follow_ups": ["recusar com cortesia", "redirecionar para humano"],
        "risks": _duplicated_number_risks(profile),
    }
