# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import base64
import hashlib
import logging
import re

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


class FleetVehicleInspection(models.Model):
    _inherit = "fleet.vehicle.inspection"

    READONLY_STATES = {
        "confirmed": [("readonly", True)],
        "cancel": [("readonly", True)],
    }

    rent_id = fields.Many2one(
        "fleet.rent",
        string="Locação",
        ondelete="set null",
        index=True,
        track_visibility="onchange",
        states=READONLY_STATES,
        help="Contrato/Proposta de locação (fleet.rent) vinculado a esta vistoria.",
    )

    unsigned_laudo_pdf = fields.Binary(
        string="Laudo Gerado (.pdf)",
        attachment=False,
        readonly=True,
        copy=False,
        help="Versão original do Laudo de Vistória gerada para o locatário assinar.",
    )
    unsigned_laudo_hash = fields.Char(
        string="Hash SHA-256 do Laudo Gerado",
        readonly=True,
        copy=False,
        help="Hash SHA-256 dos bytes exatos do Laudo de Vistória gerado.",
    )
    unsigned_laudo_generated_at = fields.Datetime(
        string="Data de Geração do Laudo",
        readonly=True,
        copy=False,
    )

    signed_laudo_pdf = fields.Binary(
        string="Laudo Assinado gov.br (.pdf)",
        attachment=False,
        readonly=True,
        copy=False,
        help="Laudo de Vistória assinado digitalmente pelo locatário via gov.br.",
    )
    signed_laudo_filename = fields.Char(
        string="Arquivo do Laudo Assinado",
        readonly=True,
        copy=False,
    )
    govbr_signature_verified = fields.Boolean(
        string="Assinatura gov.br Verificada",
        readonly=True,
        copy=False,
        track_visibility="onchange",
    )
    govbr_signer_name = fields.Char(
        string="Assinado por (Nome)",
        readonly=True,
        copy=False,
    )
    govbr_signer_cpf = fields.Char(
        string="Assinado por (CPF)",
        readonly=True,
        copy=False,
    )
    govbr_signed_date = fields.Datetime(
        string="Data de Confirmação do Laudo Assinado",
        readonly=True,
        copy=False,
    )

    senatran_driver_indicated = fields.Boolean(
        string="Condutor Indicado no SENATRAN",
        readonly=True,
        copy=False,
    )
    senatran_status_message = fields.Text(
        string="Retorno SENATRAN",
        readonly=True,
        copy=False,
    )

    def get_image_attachments(self):
        """Retorna apenas os anexos de imagem da vistoria (evitando que PDFs quebrem tags <img> no QWeb)."""
        self.ensure_one()
        return self.env["ir.attachment"].search(
            [
                ("res_model", "=", "fleet.vehicle.inspection"),
                ("res_id", "=", self.id),
                ("mimetype", "ilike", "image/%"),
            ],
            order="id asc",
        )

    def action_check_all_items_inspected(self):
        """Verifica se todos os itens da vistoria foram inspecionados (result != 'todo')."""
        self.ensure_one()
        lines = self.inspection_line_ids
        total = len(lines)
        todo_lines = lines.filtered(lambda l: l.result == "todo")
        todo_names = [
            l.inspection_item_id.name or f"Item #{l.id}" for l in todo_lines
        ]
        return {
            "all_inspected": bool(total > 0 and len(todo_lines) == 0),
            "total": total,
            "inspected": total - len(todo_lines),
            "todo": len(todo_lines),
            "todo_items": todo_names,
        }

    def action_generate_laudo_pdf(self):
        """Verifica se todos os itens foram inspecionados, gera o PDF 'Laudo de Vistória',
        armazena o hash/binário para comparação futura e retorna o PDF em base64.
        """
        self.ensure_one()
        check = self.action_check_all_items_inspected()
        if not check["all_inspected"]:
            if check["total"] == 0:
                raise UserError(
                    _("A vistoria não possui itens cadastrados para inspeção.")
                )
            raise UserError(
                _(
                    "Não é possível gerar o Laudo de Vistória: ainda existem %s item(ns) pendente(s) de inspeção (%s)."
                )
                % (check["todo"], ", ".join(check["todo_items"][:5]))
            )

        report = self.env["ir.actions.report"].sudo().search(
            [
                ("model", "=", "fleet.vehicle.inspection"),
                "|",
                ("report_name", "=", "fleet.vehicle.inspection.printable_report"),
                ("name", "ilike", "Laudo de Vist"),
            ],
            limit=1,
        )
        if not report:
            report = self.env.ref(
                "fleet_rent_inspection.action_report_fleet_vehicle_inspection_laudo",
                raise_if_not_found=False,
            )
        if not report:
            raise UserError(
                _("Relatório 'Laudo de Vistória' não encontrado no sistema.")
            )

        pdf_bytes, _ext = report.sudo().render_qweb_pdf([self.id])
        pdf_b64 = base64.b64encode(pdf_bytes).decode("ascii")
        pdf_sha256 = hashlib.sha256(pdf_bytes).hexdigest()

        self.sudo().write(
            {
                "unsigned_laudo_pdf": pdf_b64,
                "unsigned_laudo_hash": pdf_sha256,
                "unsigned_laudo_generated_at": fields.Datetime.now(),
            }
        )

        placa = (
            (self.vehicle_id.license_plate or self.vehicle_id.name or "")
            .replace("/", "_")
            .strip()
        )
        filename = (
            f"Laudo_de_Vistoria_{placa}.pdf"
            if placa
            else f"Laudo_de_Vistoria_{self.id}.pdf"
        )
        return {
            "pdf_base64": pdf_b64,
            "sha256": pdf_sha256,
            "filename": filename,
        }

    def _register_driver_in_erp(self, driver_partner):
        """Define o locatário como condutor do veículo no ERP (fleet.vehicle)."""
        self.ensure_one()
        if not self.vehicle_id or not driver_partner:
            return False

        partner_vals = {}
        if "is_driver" in self.env["res.partner"]._fields and not driver_partner.is_driver:
            partner_vals["is_driver"] = True
        if partner_vals:
            driver_partner.sudo().write(partner_vals)

        self.vehicle_id.sudo().write({"driver_id": driver_partner.id})
        _logger.info(
            "Locatário %s (ID %s) registrado como condutor do veículo %s (ID %s) no ERP.",
            driver_partner.name,
            driver_partner.id,
            self.vehicle_id.license_plate or self.vehicle_id.name,
            self.vehicle_id.id,
        )
        return True

    def _register_driver_in_senatran(self, driver_partner):
        """Realiza a indicação do locatário como Principal Condutor do veículo no SENATRAN (e-Frotas)."""
        self.ensure_one()
        vehicle = self.vehicle_id.sudo()
        if not vehicle or not driver_partner:
            return {
                "success": False,
                "message": _("Veículo ou condutor não informado."),
            }

        placa = (vehicle.license_plate or "").replace("-", "").strip().upper()
        cpf_condutor = re.sub(
            r"\D", "", driver_partner.l10n_br_cnpj_cpf or ""
        )

        if not placa:
            return {
                "success": False,
                "message": _("Veículo sem placa cadastrada para envio ao SENATRAN."),
            }
        if not cpf_condutor or len(cpf_condutor) != 11:
            return {
                "success": False,
                "message": _(
                    "CPF do condutor inválido ou ausente (%s) para indicação no SENATRAN."
                )
                % (driver_partner.l10n_br_cnpj_cpf or ""),
            }

        try:
            config = vehicle._get_efrotas_config()
            client = config.get_client(vehicle_id=vehicle.id)
            cnpj_possuidor = re.sub(
                r"\D",
                "",
                config.cnpj_filial
                or config.cnpj
                or (vehicle.company_id.partner_id.l10n_br_cnpj_cpf or ""),
            )
            payload = {
                "placaVeiculo": placa,
                "cpfPrincipalCondutor": cpf_condutor,
                "identificacaoPossuidor": cnpj_possuidor,
            }
            try:
                res = client.inserir_indicacao_principal_condutor(payload)
            except Exception as first_exc:
                err_txt = str(first_exc).lower()
                if (
                    "webhook" in err_txt
                    or "entrega de eventos" in err_txt
                    or "autorizador" in err_txt
                    or "evento obrigatório" in err_txt
                    or "evento obrigatorio" in err_txt
                ):
                    _logger.info(
                        "Cadastrando automaticamente webhook e eventos no Autorizador e-Frotas antes de reenviar indicação de condutor..."
                    )
                    config.sudo().ensure_webhook_and_events_registered()
                    res = client.inserir_indicacao_principal_condutor(payload)
                else:
                    raise
            msg = (
                res.get("mensagem")
                or res.get("mensagemTecnica")
                or str(res)
                if isinstance(res, dict)
                else str(res)
            )
            protocol = (
                (
                    res.get("chaveIndicacao")
                    or res.get("protocolo")
                    or res.get("id")
                    or msg
                )
                if isinstance(res, dict)
                else str(res)
            )
            self.sudo().write(
                {
                    "senatran_driver_indicated": True,
                    "senatran_status_message": msg,
                }
            )
            return {
                "success": True,
                "message": msg or _("Indicação enviada com sucesso ao SENATRAN."),
                "protocol": str(protocol)[:120] if protocol else "",
                "response": res,
            }
        except Exception as exc:
            err_msg = str(exc)
            _logger.warning(
                "Aviso/erro ao indicar condutor %s para veículo %s no SENATRAN: %s",
                cpf_condutor,
                placa,
                err_msg,
            )
            self.sudo().write(
                {
                    "senatran_driver_indicated": False,
                    "senatran_status_message": err_msg,
                }
            )
            return {
                "success": False,
                "message": err_msg,
                "protocol": "",
            }

    def action_retry_senatran_driver_indication(self):
        """Botão para cadastrar automaticamente o Webhook no Autorizador e-Frotas e reenviar a indicação do condutor."""
        self.ensure_one()
        driver_partner = self.inspected_by or (
            self.rent_id.tenant_id if self.rent_id else False
        )
        if not driver_partner:
            raise UserError(
                _("Informe o locatário (Inspecionado por) antes de indicar no SENATRAN.")
            )
        self._register_driver_in_erp(driver_partner)
        try:
            config = self.vehicle_id.sudo()._get_efrotas_config()
            config.sudo().ensure_webhook_and_events_registered()
        except Exception as wh_exc:
            _logger.warning("Aviso ao garantir webhook antes da indicação: %s", wh_exc)

        res = self._register_driver_in_senatran(driver_partner)
        if self.rent_id and res.get("protocol"):
            self.rent_id.sudo().write({"driver_reg_protocol": res["protocol"]})
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("SENATRAN e-Frotas"),
                "message": res.get("message") or _("Processado"),
                "type": "success" if res.get("success") else "warning",
                "sticky": True,
                "next": {"type": "ir.actions.client", "tag": "reload"},
            },
        }

    def action_confirm_with_signed_report(
        self, signed_pdf_b64, filename=None, signer_info=None
    ):
        """Confirma a vistoria mediante o Laudo de Vistória assinado via gov.br,
        anexa o documento, define o locatário como condutor no ERP e aciona o SENATRAN.
        """
        self.ensure_one()
        signer_info = signer_info or {}

        check = self.action_check_all_items_inspected()
        if not check["all_inspected"]:
            raise UserError(
                _(
                    "A vistoria não pode ser confirmada pois ainda há itens pendentes de inspeção."
                )
            )

        placa = (
            (self.vehicle_id.license_plate or self.vehicle_id.name or "")
            .replace("/", "_")
            .strip()
        )
        if not filename:
            filename = (
                f"Laudo_de_Vistoria_{placa}_assinado.pdf"
                if placa
                else f"Laudo_de_Vistoria_{self.id}_assinado.pdf"
            )

        signer_name = signer_info.get("signer_name") or (
            self.inspected_by.name if self.inspected_by else ""
        )
        signer_cpf = signer_info.get("signer_cpf") or (
            self.inspected_by.l10n_br_cnpj_cpf if self.inspected_by else ""
        )

        # 1. Atualiza campos do laudo assinado e confirma a vistoria
        self.sudo().write(
            {
                "signed_laudo_pdf": signed_pdf_b64,
                "signed_laudo_filename": filename,
                "govbr_signature_verified": True,
                "govbr_signer_name": signer_name,
                "govbr_signer_cpf": signer_cpf,
                "govbr_signed_date": fields.Datetime.now(),
            }
        )

        if self.state == "draft":
            self.sudo().button_confirm()

        # 2. Cria anexo do PDF assinado e registra no chatter da vistoria
        att_vals = {
            "name": filename,
            "type": "binary",
            "datas": signed_pdf_b64,
            "res_model": "fleet.vehicle.inspection",
            "res_id": self.id,
            "mimetype": "application/pdf",
        }
        attachment = self.env["ir.attachment"].sudo().create(att_vals)

        # 3. Define o locatário como condutor no ERP (fleet.vehicle)
        driver_partner = self.inspected_by or (
            self.rent_id.tenant_id if self.rent_id else False
        )
        erp_driver_ok = False
        if driver_partner:
            erp_driver_ok = self._register_driver_in_erp(driver_partner)

        # 4. Atribui condução no SENATRAN (e-Frotas)
        senatran_res = {"success": False, "message": _("Não executado")}
        if driver_partner:
            senatran_res = self._register_driver_in_senatran(driver_partner)

        # 5. Atualiza o contrato/locação (fleet.rent) vinculado, se houver
        rent = self.rent_id.sudo() if self.rent_id else False
        if not rent and self.vehicle_id and driver_partner:
            rent = (
                self.env["fleet.rent"]
                .sudo()
                .search(
                    [
                        ("vehicle_id", "=", self.vehicle_id.id),
                        ("tenant_id", "=", driver_partner.id),
                        (
                            "state",
                            "in",
                            ["contract_signed", "waiting_inspection", "inspected"],
                        ),
                    ],
                    order="id desc",
                    limit=1,
                )
            )
            if rent:
                self.sudo().write({"rent_id": rent.id})

        if rent:
            rent_Attachment = (
                self.env["ir.attachment"]
                .sudo()
                .create(
                    {
                        "name": filename,
                        "type": "binary",
                        "datas": signed_pdf_b64,
                        "res_model": "fleet.rent",
                        "res_id": rent.id,
                        "mimetype": "application/pdf",
                    }
                )
            )
            if rent.state in ("contract_signed", "waiting_inspection"):
                rent.action_confirm_inspected()
            if rent.state == "inspected":
                rent.action_indicate_driver_senatran()
            if senatran_res.get("protocol"):
                rent.write({"driver_reg_protocol": senatran_res["protocol"]})

            rent_msg = _(
                "<b>Vistoria de Abertura Confirmada (%s)</b><br/>"
                "<ul>"
                "<li><b>Laudo Assinado (gov.br):</b> %s</li>"
                "<li><b>Assinante:</b> %s (%s)</li>"
                "<li><b>Condutor registrado no ERP:</b> %s</li>"
                "<li><b>Indicação SENATRAN (e-Frotas):</b> %s (%s)</li>"
                "</ul>"
            ) % (
                self.name,
                filename,
                signer_name or "-",
                signer_cpf or "-",
                _("Sim") if erp_driver_ok else _("Não"),
                _("Enviada") if senatran_res.get("success") else _("Pendente / Aviso"),
                senatran_res.get("message") or "-",
            )
            rent.message_post(
                body=rent_msg,
                attachment_ids=[rent_Attachment.id],
            )

        insp_msg = _(
            "<b>Vistoria confirmada mediante Laudo Assinado gov.br</b><br/>"
            "<ul>"
            "<li><b>Arquivo:</b> %s</li>"
            "<li><b>Assinante gov.br:</b> %s (CPF: %s)</li>"
            "<li><b>Condutor definido no ERP:</b> %s</li>"
            "<li><b>SENATRAN (e-Frotas):</b> %s</li>"
            "</ul>"
        ) % (
            filename,
            signer_name or "-",
            signer_cpf or "-",
            driver_partner.name if (erp_driver_ok and driver_partner) else "-",
            senatran_res.get("message") or "-",
        )
        self.sudo().message_post(
            body=insp_msg,
            attachment_ids=[attachment.id],
        )

        return {
            "success": True,
            "inspection_id": self.id,
            "state": self.state,
            "rent_id": rent.id if rent else False,
            "rent_state": rent.state if rent else False,
            "erp_driver_registered": erp_driver_ok,
            "senatran": senatran_res,
        }
