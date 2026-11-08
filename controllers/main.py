# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import json
import logging
import re

from odoo import _, fields, http
from odoo.http import request

_logger = logging.getLogger(__name__)


class EfrotasWebhookController(http.Controller):
    @http.route(
        ["/efrotas/webhook", "/efrotas/webhook/<path:subpath>"],
        type="http",
        auth="public",
        methods=["GET", "POST", "PUT"],
        csrf=False,
    )
    def efrotas_webhook(self, **kwargs):
        """Endpoint de Webhook exigido pelo Autorizador e-Frotas SENATRAN para entrega de eventos
        (ex: código 12 = Solicitação Principal Condutor, código 13 = Resposta/Aceite Principal Condutor,
        código 16 = Cancelamento Principal Condutor).
        """
        raw_body = ""
        payload = {}
        try:
            raw_body = request.httprequest.get_data(as_text=True) or ""
            if raw_body:
                payload = json.loads(raw_body)
        except Exception:
            payload = dict(kwargs or {})

        _logger.info("Webhook e-Frotas SENATRAN recebido: %s", raw_body[:2000])

        try:
            if "efrotas.log" in request.env:
                request.env["efrotas.log"].sudo().create(
                    {
                        "endpoint": "/efrotas/webhook",
                        "method": request.httprequest.method,
                        "status_code": 200,
                        "duration": 0.0,
                        "request_payload": raw_body[:50000],
                        "response_payload": '{"status": "ok"}',
                    }
                )
        except Exception as log_exc:
            _logger.warning("Aviso ao gravar log do webhook e-Frotas: %s", log_exc)

        # Processa eventos de Principal Condutor se houver placa no payload
        try:
            events = payload if isinstance(payload, list) else [payload]
            for ev in events:
                if not isinstance(ev, dict):
                    continue
                codigo = ev.get("codigo") or ev.get("codigoEvento")
                placa = (
                    ev.get("placa")
                    or ev.get("placaVeiculo")
                    or (
                        ev.get("dados", {}).get("placa")
                        if isinstance(ev.get("dados"), dict)
                        else None
                    )
                )
                if placa:
                    clean_placa = re.sub(r"[^A-Za-z0-9]", "", str(placa)).upper()
                    vehicle = (
                        request.env["fleet.vehicle"]
                        .sudo()
                        .search(
                            [("license_plate", "ilike", clean_placa)], limit=1
                        )
                    )
                    if vehicle:
                        rent = (
                            request.env["fleet.rent"]
                            .sudo()
                            .search(
                                [
                                    ("vehicle_id", "=", vehicle.id),
                                    (
                                        "state",
                                        "in",
                                        ["inspected", "waiting_senatran"],
                                    ),
                                ],
                                order="id desc",
                                limit=1,
                            )
                        )
                        if rent:
                            if str(codigo) == "13":
                                rent.action_confirm_driver_registered()
                            rent.message_post(
                                body=_(
                                    "<b>Evento Webhook SENATRAN e-Frotas recebido (Código %s):</b><br/><pre>%s</pre>"
                                )
                                % (
                                    codigo or "-",
                                    json.dumps(
                                        ev, indent=2, ensure_ascii=False
                                    ),
                                )
                            )
        except Exception as proc_exc:
            _logger.warning(
                "Erro ao processar evento do webhook e-Frotas: %s", proc_exc
            )

        headers = [("Content-Type", "application/json")]
        return request.make_response(
            json.dumps({"status": "ok", "mensagem": "Evento recebido com sucesso"}),
            headers=headers,
            status=200,
        )
