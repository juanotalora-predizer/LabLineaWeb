RowLevelSecurity
-- 1. Habilitar RLS en las tablas multi-tenant críticas
ALTER TABLE paciente ENABLE ROW LEVEL SECURITY;
ALTER TABLE orden ENABLE ROW LEVEL SECURITY;
ALTER TABLE empresa ENABLE ROW LEVEL SECURITY;
ALTER TABLE analisis ENABLE ROW LEVEL SECURITY;
ALTER TABLE analisis_por_orden ENABLE ROW LEVEL SECURITY;
ALTER TABLE diagnostico ENABLE ROW LEVEL SECURITY;
ALTER TABLE usuarios ENABLE ROW LEVEL SECURITY;

-- 2. Crear las Políticas de Seguridad (Filtro automático por la variable de sesión 'app.current_tenant')
CREATE POLICY tenant_isolation_policy_paciente ON paciente
USING (tenant_id = current_setting('app.current_tenant', true));

CREATE POLICY tenant_isolation_policy_orden ON orden
USING (tenant_id = current_setting('app.current_tenant', true));

CREATE POLICY tenant_isolation_policy_empresa ON empresa
USING (tenant_id = current_setting('app.current_tenant', true));

CREATE POLICY tenant_isolation_policy_analisis ON analisis
USING (tenant_id = current_setting('app.current_tenant', true));

CREATE POLICY tenant_isolation_policy_apo ON analisis_por_orden
USING (tenant_id = current_setting('app.current_tenant', true));

CREATE POLICY tenant_isolation_policy_diag ON diagnostico
USING (tenant_id = current_setting('app.current_tenant', true));

CREATE POLICY tenant_isolation_policy_usuarios ON usuarios
USING (tenant_id = current_setting('app.current_tenant', true));
