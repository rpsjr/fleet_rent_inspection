# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

{
    "name": "Fleet Rent Inspection & SENATRAN Driver Integration",
    "version": "13.0.1.0.0",
    "category": "Fleet",
    "summary": (
        "Relaciona fleet.vehicle.inspection com fleet.rent, gera vistoria de "
        "Abertura de locação para o locatário e registra condutor no ERP e SENATRAN."
    ),
    "author": "Babur / OCA",
    "license": "AGPL-3",
    "depends": [
        "fleet",
        "fleet_rent",
        "fleet_rent_ext",
        "fleet_vehicle_inspection",
        "fleet_vehicle_inspection_template",
        "l10_br_fleet_efrotas",
    ],
    "data": [
        "security/ir.model.access.csv",
        "data/inspection_template_data.xml",
        "views/efrotas_config_views.xml",
        "views/fleet_vehicle_inspection_views.xml",
        "views/fleet_rent_views.xml",
        "report/fleet_vehicle_inspection_report.xml",
    ],
    "installable": True,
    "application": False,
}
