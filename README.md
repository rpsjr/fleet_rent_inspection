# Fleet Rent Inspection & SENATRAN Driver Integration (`fleet_rent_inspection`)

Módulo Odoo 13 para integração entre:
- **Locação de Frota (`fleet.rent` / `fleet_rent_ext`)**
- **Vistoria Veicular (`fleet.vehicle.inspection` / `fleet_vehicle_inspection_template`)**
- **SENATRAN e-Frotas (`l10_br_fleet_efrotas`)**

## Funcionalidades

1. **Relacionamento `fleet.vehicle.inspection` <-> `fleet.rent`**:
   - Adiciona o campo `rent_id` em `fleet.vehicle.inspection` (formulário, árvore e filtros de pesquisa).
2. **Geração de Vistoria em `fleet.rent`**:
   - Botão **Gerar Vistoria** (`action_generate_inspection`) que cria a vistoria vinculada à locação com:
     - **Modelo de Inspeção**: `Abertura de locação`
     - **Inspecionado por**: Locatário (`tenant_id`)
     - Estrutura preparada (`TODO`) para envio do link do `vehicle-inspection-app` por WhatsApp.
3. **Confirmação mediante Laudo Assinado (gov.br) e Registro de Condutor**:
   - Armazena o Laudo gerado e o Laudo assinado via gov.br.
   - Confirma a inspeção (`state = 'confirmed'`).
   - Registra o locatário como condutor do veículo no ERP (`fleet.vehicle.driver_id`).
   - Envia a indicação de Principal Condutor para o SENATRAN via API Transacional do e-Frotas (`/transacional/v1/principalcondutor/indicacoes/inserir`).

