# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import logging

from odoo import _, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class EfrotasConfig(models.Model):
    _inherit = "efrotas.config"

    webhook_url = fields.Char(
        string="URL do Webhook de Eventos",
        default=lambda self: self._default_webhook_url(),
        help="URL pública para onde o SENATRAN e-Frotas enviará notificações de eventos (Autorizador e-Frotas).",
    )
    webhook_header = fields.Char(
        string="Header de Autenticação do Webhook",
        default="x-efrotas-token",
    )
    webhook_token = fields.Char(
        string="Valor do Header do Webhook",
        default="babur-efrotas-webhook",
    )
    webhook_registered = fields.Boolean(
        string="Webhook Cadastrado no SENATRAN",
        readonly=True,
    )
    webhook_last_sync = fields.Datetime(
        string="Último Cadastro do Webhook",
        readonly=True,
    )

    def _default_webhook_url(self):
        base_url = (
            self.env["ir.config_parameter"]
            .sudo()
            .get_param("web.base.url", "https://babur.com.br")
        )
        if not base_url or "localhost" in base_url or "127.0.0.1" in base_url:
            base_url = "https://babur.com.br"
        if base_url.startswith("http://"):
            base_url = "https://" + base_url[len("http://") :]
        return f"{base_url.rstrip('/')}/efrotas/webhook"

    def ensure_webhook_and_events_registered(self):
        """Cadastra o endpoint de webhook no Autorizador e-Frotas (/autorizador/v1/endpoint)
        e ativa os eventos obrigatórios (/autorizador/v1/eventos) para permitir indicação de Principal Condutor.
        """
        self.ensure_one()
        client = self.get_client()
        url = (self.webhook_url or self._default_webhook_url()).strip()
        if url.startswith("http://"):
            url = "https://" + url[len("http://") :]

        endpoint_payload = {
            "url": url,
            "header": (self.webhook_header or "").strip(),
            "valor": (self.webhook_token or "").strip(),
        }
        ep_res = client.create_endpoint(endpoint_payload)

        # Consulta todos os eventos permitidos e marca todos como ativos
        ev_res = {}
        try:
            ev_data = client.get_eventos(todos=True)
            if isinstance(ev_data, dict) and isinstance(
                ev_data.get("eventosPermitidos"), list
            ):
                for ev in ev_data["eventosPermitidos"]:
                    if isinstance(ev, dict):
                        ev["ativo"] = True
                ev_res = client.save_eventos(ev_data)
        except Exception as ev_exc:
            _logger.warning(
                "Aviso ao ativar eventos no Autorizador e-Frotas: %s", ev_exc
            )

        self.sudo().write(
            {
                "webhook_url": url,
                "webhook_registered": True,
                "webhook_last_sync": fields.Datetime.now(),
            }
        )
        return {
            "endpoint_response": ep_res,
            "eventos_response": ev_res,
            "webhook_url": url,
        }

    def action_register_webhook(self):
        """Botão na tela de Configuração e-Frotas para cadastrar o Webhook e ativar eventos no SENATRAN."""
        self.ensure_one()
        try:
            res = self.ensure_webhook_and_events_registered()
            ep_msg = (
                res["endpoint_response"].get("mensagem")
                if isinstance(res.get("endpoint_response"), dict)
                else str(res.get("endpoint_response"))
            )
            msg = _(
                "Webhook (%s) e eventos obrigatórios cadastrados com sucesso no Autorizador e-Frotas! (%s)"
            ) % (res["webhook_url"], ep_msg or "OK")
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": _("Autorizador e-Frotas SENATRAN"),
                    "message": msg,
                    "type": "success",
                    "sticky": False,
                    "next": {
                        "type": "ir.actions.client",
                        "tag": "reload",
                    },
                },
            }
        except Exception as exc:
            raise UserError(
                _("Falha ao cadastrar Webhook no Autorizador e-Frotas: %s")
                % str(exc)
            )

