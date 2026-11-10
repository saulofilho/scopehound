"""Guardrails: regras de segurança impostas fora do modelo.

Seguindo o Burp AT, escopo, acesso a ferramentas e limites vivem na camada
de ferramentas, separada do modelo. Nenhum prompt muda o que este pacote
decide.
"""

from .budget import Budget
from .egress import AuditEvent, Egress, EgressResult, RedirectChain, Resolver, system_resolver
from .errors import (
    BudgetExhausted,
    EgressDenied,
    EgressNetworkError,
    GuardrailError,
    KillSwitchTripped,
    ScopeViolation,
    ToolArgsDenied,
)
from .ippolicy import ALWAYS_DENIED, DEFAULT_INTERNAL, IpPolicy, canonical_ip
from .killswitch import KillSwitch
from .ratelimit import RateLimiter
from .scope import Scope, Target, check_method, check_url, load_scope, normalize_path
from .toolargs import sanitize_sqlmap_args
from .verification import PocVerdict, evaluate_poc

__all__ = [
    "ALWAYS_DENIED",
    "DEFAULT_INTERNAL",
    "AuditEvent",
    "Budget",
    "BudgetExhausted",
    "Egress",
    "EgressDenied",
    "EgressNetworkError",
    "EgressResult",
    "GuardrailError",
    "IpPolicy",
    "KillSwitch",
    "KillSwitchTripped",
    "PocVerdict",
    "RateLimiter",
    "RedirectChain",
    "Resolver",
    "Scope",
    "ScopeViolation",
    "Target",
    "ToolArgsDenied",
    "canonical_ip",
    "check_method",
    "check_url",
    "evaluate_poc",
    "load_scope",
    "normalize_path",
    "sanitize_sqlmap_args",
    "system_resolver",
]
