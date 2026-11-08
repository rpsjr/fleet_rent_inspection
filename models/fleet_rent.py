# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class FleetRent(models.Model):
    _inherit = "fleet.rent"

    inspection_ids = fields.One2many(
        "fleet.vehicle.inspection",
        "rent_id",
        string="Vistorias",
        help="Vistorias veiculares vinculadas a esta locação.",
    )
    inspection_id = fields.Many2one(
        "fleet.vehicle.inspection",
        string="Vistoria de Abertura",
        copy=False,
        ondelete="set null",
        help="Vistoria de abertura de locação realizada pelo locatário.",
    )
    inspection_count = fields.Integer(
        string="Qtd. Vistorias",
        compute="_compute_inspection_count",
    )

    @api.depends("inspection_ids", "inspection_id")
    def _compute_inspection_count(self):
        for rent in self:
            ids = set(rent.inspection_ids.ids)
            if rent.inspection_id:
                ids.add(rent.inspection_id.id)
            rent.inspection_count = len(ids)

    def _get_opening_inspection_template(self):
        """Busca o Modelo de Inspeção 'Abertura de locação'."""
        Template = self.env["fleet.vehicle.inspection.template"]
        template = Template.search(
            [("name", "=ilike", "Abertura de locação")], limit=1
        )
        if not template:
            template = Template.search(
                [("name", "ilike", "Abertura de loca")], limit=1
            )
        if not template:
            template = self.env.ref(
                "fleet_rent_inspection.inspection_template_abertura_locacao",
                raise_if_not_found=False,
            )
        return template

    def _send_inspection_whatsapp_todo(self, inspection):
        """TODO: Enviar WhatsApp para o locatário com link para o vehicle-inspection-app."""
        self.ensure_one()
        app_base_url = (
            self.env["ir.config_parameter"]
            .sudo()
            .get_param(
                "vehicle_inspection_app.base_url",
                "https://vistoria.babur.com.br",
            )
        )
        inspection_url = f"{app_base_url.rstrip('/')}/inspection/{inspection.id}"
        phone = (
            (self.tenant_id.mobile or self.tenant_id.phone or "")
            if self.tenant_id
            else ""
        )

        # TODO: Enviar WhatsApp com link para o locatário realizar a vistoria no vehicle-inspection-app
        # Exemplo de integração futura com whatsapp.message (meta_whatsapp):
        # if "whatsapp.message" in self.env and phone:
        #     wa_template = self.env.ref("...", raise_if_not_found=False)
        #     msg = self.env["whatsapp.message"].create({
        #         "body": f"Olá {self.tenant_id.name}, realize a vistoria do veículo {self.vehicle_id.name} em: {inspection_url}",
        #         "mobile_number": phone,
        #         "partner_id": self.tenant_id.id,
        #         "res_model": "fleet.vehicle.inspection",
        #         "res_id": inspection.id,
        #         "status": "draft",
        #     })
        #     msg.action_send()

        _logger.info(
            "TODO WhatsApp Vistoria: enviar link %s para locatário %s (tel: %s)",
            inspection_url,
            self.tenant_id.name if self.tenant_id else "-",
            phone,
        )
        return inspection_url

    def _create_opening_inspection_record(self):
        """Cria o registro fleet.vehicle.inspection com Modelo = 'Abertura de locação'
        e Inspecionado por = Locatário (tenant_id).
        """
        self.ensure_one()
        if not self.vehicle_id:
            raise UserError(
                _("Selecione o veículo da locação antes de gerar a vistoria.")
            )
        if not self.tenant_id:
            raise UserError(
                _("Selecione o locatário (tenant_id) antes de gerar a vistoria.")
            )

        existing = self.inspection_ids.filtered(
            lambda i: i.state != "cancel" and i.direction == "out"
        )
        if existing:
            inspection = existing[0]
            if not self.inspection_id:
                self.write({"inspection_id": inspection.id})
            return inspection

        template = self._get_opening_inspection_template()
        inspection_lines = []
        if template and template.inspection_template_line_ids:
            for line in template.inspection_template_line_ids:
                inspection_lines.append(
                    (
                        0,
                        0,
                        {
                            "inspection_item_id": line.inspection_template_item_id.id,
                            "state": "draft",
                        },
                    )
                )

        odometer_val = self.odometer or self.vehicle_id.odometer or 0.0
        vals = {
            "rent_id": self.id,
            "vehicle_id": self.vehicle_id.id,
            "inspected_by": self.tenant_id.id,
            "direction": "out",
            "date_inspected": fields.Datetime.now(),
            "inspection_template_id": template.id if template else False,
            "note": template.note if template else False,
            "inspection_line_ids": inspection_lines,
        }
        if odometer_val > 0:
            vals["odometer"] = odometer_val

        inspection = self.env["fleet.vehicle.inspection"].create(vals)
        if self.tenant_id:
            inspection.message_subscribe(partner_ids=[self.tenant_id.id])

        self.write({"inspection_id": inspection.id})
        inspection_url = self._send_inspection_whatsapp_todo(inspection)

        self.message_post(
            body=_(
                "<b>Vistoria de Abertura de Locação gerada:</b> "
                "<a href='#' data-oe-model='fleet.vehicle.inspection' data-oe-id='%d'>%s</a><br/>"
                "<ul>"
                "<li><b>Modelo de Inspeção:</b> %s</li>"
                "<li><b>Inspecionado por (Locatário):</b> %s</li>"
                "<li><b>Link do App (TODO envio WhatsApp):</b> <code>%s</code></li>"
                "</ul>"
            )
            % (
                inspection.id,
                inspection.name,
                template.name if template else _("Abertura de locação"),
                self.tenant_id.name,
                inspection_url,
            )
        )
        return inspection

    def action_generate_inspection(self):
        """Botão/função em fleet.rent para gerar vistoria (Modelo = Abertura de locação,
        Inspecionado por = Locatário) e atualizar status para Aguardando Vistoria.
        """
        created_inspections = self.env["fleet.vehicle.inspection"]
        for rent in self:
            inspection = rent._create_opening_inspection_record()
            created_inspections |= inspection
            vals = {}
            if not rent.inspection_scheduled_date:
                vals["inspection_scheduled_date"] = fields.Datetime.now()
            if rent.state in (
                "draft",
                "proposal_sent",
                "crlv_shared",
                "waiting_signature",
                "contract_signed",
            ):
                vals["state"] = "waiting_inspection"
            if vals:
                rent.write(vals)
            if rent.vehicle_id and rent.vehicle_id.state != "inspection":
                rent.vehicle_id.state = "inspection"

        if len(created_inspections) == 1:
            return {
                "name": _("Vistoria de Abertura de Locação"),
                "type": "ir.actions.act_window",
                "res_model": "fleet.vehicle.inspection",
                "view_mode": "form",
                "res_id": created_inspections.id,
                "target": "current",
            }
        return True

    def action_schedule_inspection(self):
        """Estende o botão 'Agendar Vistoria' do BPMN para também gerar a vistoria de Abertura de locação."""
        res = super(FleetRent, self).action_schedule_inspection()
        for rent in self:
            if not rent.inspection_ids.filtered(lambda i: i.state != "cancel"):
                rent._create_opening_inspection_record()
        return res

    def action_indicate_driver_senatran(self):
        """Estende a transição para também definir o locatário como condutor no ERP e acionar o SENATRAN."""
        res = super(FleetRent, self).action_indicate_driver_senatran()
        for rent in self:
            if rent.vehicle_id and rent.tenant_id:
                insp = rent.inspection_id or (
                    rent.inspection_ids[:1] if rent.inspection_ids else False
                )
                if insp:
                    insp._register_driver_in_erp(rent.tenant_id)
                    if not insp.senatran_driver_indicated:
                        sen_res = insp._register_driver_in_senatran(
                            rent.tenant_id
                        )
                        if sen_res.get("protocol") and not rent.driver_reg_protocol:
                            rent.write(
                                {"driver_reg_protocol": sen_res["protocol"]}
                            )
                else:
                    rent.vehicle_id.sudo().write(
                        {"driver_id": rent.tenant_id.id}
                    )
        return res

    def action_view_inspections(self):
        """Abre as vistorias vinculadas à locação."""
        self.ensure_one()
        ids = set(self.inspection_ids.ids)
        if self.inspection_id:
            ids.add(self.inspection_id.id)
        id_list = list(ids)

        if len(id_list) == 1:
            return {
                "name": _("Vistoria"),
                "type": "ir.actions.act_window",
                "res_model": "fleet.vehicle.inspection",
                "view_mode": "form",
                "res_id": id_list[0],
                "context": {
                    "default_rent_id": self.id,
                    "default_vehicle_id": self.vehicle_id.id,
                    "default_inspected_by": self.tenant_id.id,
                },
            }
        return {
            "name": _("Vistorias da Locação"),
            "type": "ir.actions.act_window",
            "res_model": "fleet.vehicle.inspection",
            "view_mode": "tree,form",
            "domain": [("id", "in", id_list)],
            "context": {
                "default_rent_id": self.id,
                "default_vehicle_id": self.vehicle_id.id,
                "default_inspected_by": self.tenant_id.id,
            },
        }
