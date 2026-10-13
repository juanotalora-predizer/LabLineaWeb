DDL Originial Lablinea
-- [analisis por orden] definition
-- Drop table
-- DROP TABLE [analisis por orden];
CREATE TABLE [analisis por orden] ( [consecutivo] INTEGER NOT NULL, [analisis] INTEGER NOT NULL, [numero de orden] INTEGER NOT NULL, [tipo tarifa] VARCHAR(15) NOT NULL, [costo real] DECIMAL(100,4), [TipoProcedimiento] VARCHAR(1) DEFAULT '1', [ClaseProcedimiento] VARCHAR(1) DEFAULT '1', [CantidadProcedimiento] SMALLINT DEFAULT 1, [FechaProcedimiento] TIMESTAMP DEFAULT Date(), [observaciones] VARCHAR(255), [UsuarioDigitacion] VARCHAR(50), [FechaDigitacion] TIMESTAMP DEFAULT Date(), [HoraDigitacion] TIMESTAMP DEFAULT Now(), [FirstPrint] TIMESTAMP, [LastPrint] TIMESTAMP, [PrintTimes] SMALLINT DEFAULT 0, CONSTRAINT SYS_PK_10866 PRIMARY KEY ([consecutivo]) ); CREATE INDEX [ANALISIS POR ORDEN_ANALISIS] ON [analisis por orden] ([analisis]); CREATE INDEX [ANALISIS POR ORDEN_INDEX1] ON [analisis por orden] ([numero de orden],[analisis]); CREATE INDEX [ANALISIS POR ORDEN_ORDEN] ON [analisis por orden] ([numero de orden]); CREATE INDEX [ANALISIS POR ORDEN_TIPO TARIFA] ON [analisis por orden] ([tipo tarifa]); CREATE UNIQUE INDEX SYS_IDX_SYS_PK_10866_10867 ON [analisis por orden] ([consecutivo]);
-- [banco] definition
-- Drop table
-- DROP TABLE [banco];
CREATE TABLE [banco] ( [Codigo] SMALLINT NOT NULL, [Descripcion] VARCHAR(50) NOT NULL, CONSTRAINT SYS_PK_10874 PRIMARY KEY ([Codigo]) ); CREATE UNIQUE INDEX SYS_IDX_SYS_PK_10874_10875 ON [banco] ([Codigo]);
-- [Ciudades] definition
-- Drop table
-- DROP TABLE [Ciudades];
CREATE TABLE [Ciudades] ( [cgocdad] VARCHAR(5) NOT NULL, [nombre] VARCHAR(50), [cgodpto] VARCHAR(2), CONSTRAINT SYS_PK_10881 PRIMARY KEY ([cgocdad]) ); CREATE INDEX CIUDADES_CGODPTO ON [Ciudades] ([cgodpto]); CREATE UNIQUE INDEX SYS_IDX_SYS_PK_10881_10882 ON [Ciudades] ([cgocdad]);
-- [ClaseProcedimiento] definition
-- Drop table
-- DROP TABLE [ClaseProcedimiento];
CREATE TABLE [ClaseProcedimiento] ( [codigo] VARCHAR(1) NOT NULL, [nombre] VARCHAR(50) NOT NULL, CONSTRAINT SYS_PK_10886 PRIMARY KEY ([codigo]) ); CREATE UNIQUE INDEX SYS_IDX_SYS_PK_10886_10887 ON [ClaseProcedimiento] ([codigo]);
-- [Codes] definition
-- Drop table
-- DROP TABLE [Codes];
CREATE TABLE [Codes] ( [Code_Desc] VARCHAR(15) NOT NULL, [Last_Nbr_Assigned] INTEGER DEFAULT 0 NOT NULL, CONSTRAINT SYS_PK_10893 PRIMARY KEY ([Code_Desc]) ); CREATE UNIQUE INDEX SYS_IDX_SYS_PK_10893_10894 ON [Codes] ([Code_Desc]);
-- [CondicionUsuaria] definition
-- Drop table
-- DROP TABLE [CondicionUsuaria];
CREATE TABLE [CondicionUsuaria] ( [codigo] VARCHAR(1) NOT NULL, [nombre] VARCHAR(50) NOT NULL, CONSTRAINT SYS_PK_10909 PRIMARY KEY ([codigo]) ); CREATE UNIQUE INDEX SYS_IDX_SYS_PK_10909_10910 ON [CondicionUsuaria] ([codigo]);
-- [doctor] definition
-- Drop table
-- DROP TABLE [doctor];
CREATE TABLE [doctor] ( [consecutivo] INTEGER NOT NULL, [cc] VARCHAR(10), [apellidos] VARCHAR(30) NOT NULL, [nombres] VARCHAR(30) NOT NULL, [tel] VARCHAR(50), [dir] VARCHAR(50), [entidad donde trabaja] VARCHAR(100), [Fax] VARCHAR(15), [Email] VARCHAR(50), [DireccionAlterna] VARCHAR(50), [Secretaria] VARCHAR(50), [TelefonoAlterno] VARCHAR(25), [UsuarioDigitacion] VARCHAR(50), [FechaDigitacion] TIMESTAMP DEFAULT Date(), [UsuarioLastUpdate] VARCHAR(50), [FechaLastUpdate] TIMESTAMP, CONSTRAINT SYS_PK_10933 PRIMARY KEY ([consecutivo]) ); CREATE UNIQUE INDEX SYS_IDX_SYS_PK_10933_10934 ON [doctor] ([consecutivo]);
-- [empresa] definition
-- Drop table
-- DROP TABLE [empresa];
CREATE TABLE [empresa] ( [consecutivo] INTEGER NOT NULL, [nit] VARCHAR(50), [descripcion] VARCHAR(50) NOT NULL, [tel] VARCHAR(50), [dir] VARCHAR(50), [descuento] NUMERIC(100,1) DEFAULT 0.1 NOT NULL, [codigoSGSS] VARCHAR(10), [contrato] VARCHAR(10), [planbeneficios] VARCHAR(30), [poliza] VARCHAR(10), [UsuarioDigitacion] VARCHAR(50), [FechaDigitacion] TIMESTAMP DEFAULT Date(), [UsuarioLastUpdate] VARCHAR(50), [FechaLastUpdate] TIMESTAMP, [NeedCopago] BOOLEAN DEFAULT false, CONSTRAINT SYS_PK_10940 PRIMARY KEY ([consecutivo]) ); CREATE INDEX EMPRESA_CODIGOSGSS ON [empresa] ([codigoSGSS]); CREATE UNIQUE INDEX SYS_IDX_SYS_PK_10940_10941 ON [empresa] ([consecutivo]);
-- [forma de pago] definition
-- Drop table
-- DROP TABLE [forma de pago];
CREATE TABLE [forma de pago] ( [consecutivo] INTEGER NOT NULL, [descripcion] VARCHAR(10) NOT NULL, CONSTRAINT SYS_PK_10948 PRIMARY KEY ([consecutivo]) ); CREATE UNIQUE INDEX SYS_IDX_SYS_PK_10948_10949 ON [forma de pago] ([consecutivo]);
-- [GrupoAntEspecial] definition
-- Drop table
-- DROP TABLE [GrupoAntEspecial];
CREATE TABLE [GrupoAntEspecial] ( [codigo] VARCHAR(1) NOT NULL, [nombre] VARCHAR(50) NOT NULL, CONSTRAINT SYS_PK_10954 PRIMARY KEY ([codigo]) ); CREATE UNIQUE INDEX SYS_IDX_SYS_PK_10954_10955 ON [GrupoAntEspecial] ([codigo]);
-- [MSysCompactError] definition
-- Drop table
-- DROP TABLE [MSysCompactError];
CREATE TABLE [MSysCompactError] ( [ErrorCode] INTEGER, [ErrorDescription] VARCHAR(16777216), [ErrorTable] VARCHAR(255), [ErrorRecid] BLOB );
-- [Ocupaciones] definition
-- Drop table
-- DROP TABLE [Ocupaciones];
CREATE TABLE [Ocupaciones] ( [codigo] VARCHAR(3) NOT NULL, [nombre] VARCHAR(250), CONSTRAINT SYS_PK_10982 PRIMARY KEY ([codigo]) ); CREATE UNIQUE INDEX SYS_IDX_SYS_PK_10982_10983 ON [Ocupaciones] ([codigo]);
-- [paciente] definition
-- Drop table
-- DROP TABLE [paciente];
CREATE TABLE [paciente] ( [consecutivo] INTEGER NOT NULL, [TipoId] VARCHAR(3) DEFAULT CC, [cc] VARCHAR(50), [apellidos] VARCHAR(30) NOT NULL, [nombres] VARCHAR(25) NOT NULL, [SegundoApellido] VARCHAR(20), [SegundoNombre] VARCHAR(20), [tel] VARCHAR(50), [dir] VARCHAR(50), [sexo] VARCHAR(1) NOT NULL, [fecha de nacimiento] TIMESTAMP, [edad] VARCHAR(50), [UnidadEdad] VARCHAR(1) DEFAULT A, [NomTitular] VARCHAR(50), [PrntscoTitular] VARCHAR(50), [TipoUsuario] VARCHAR(1) DEFAULT P, [ZonaResidencia] VARCHAR(1) DEFAULT U, [TipoAfiliado] VARCHAR(1) DEFAULT C, [Ocupacion] VARCHAR(3), [GrpAntEsp] VARCHAR(1) DEFAULT O, [ResHabitual] VARCHAR(5) DEFAULT '76001', [CondicionUsuaria] VARCHAR(1), [UsuarioDigitacion] VARCHAR(50), [FechaDigitacion] TIMESTAMP DEFAULT Date(), [UsuarioLastUpdate] VARCHAR(50), [FechaLastUpdate] TIMESTAMP, CONSTRAINT SYS_PK_10995 PRIMARY KEY ([consecutivo]) ); CREATE INDEX PACIENTE_APELLIDOS ON [paciente] ([apellidos]); CREATE INDEX PACIENTE_TIPOID ON [paciente] ([TipoId]); CREATE UNIQUE INDEX SYS_IDX_SYS_PK_10995_10996 ON [paciente] ([consecutivo]);
-- [RegistroSoftware] definition
-- Drop table
-- DROP TABLE [RegistroSoftware];
CREATE TABLE [RegistroSoftware] ( [NitEmpresa] VARCHAR(13) NOT NULL, [CodigoSGSS] VARCHAR(10) NOT NULL, [NombreEmpresa] VARCHAR(50) NOT NULL, [DireccionActual] VARCHAR(50), [TelefonoActual] VARCHAR(15), [CiudadActual] VARCHAR(50), [Representante1] VARCHAR(50), [Cargo1] VARCHAR(50), [Representante2] VARCHAR(50), [Cargo2] VARCHAR(50), [NumRegistroSoftware] VARCHAR(20) NOT NULL, [FechaRegistro] TIMESTAMP DEFAULT Date() NOT NULL, [LicenciasPrograma] SMALLINT DEFAULT 1 NOT NULL, [MaxEmpresasRegistradas] SMALLINT DEFAULT 1 NOT NULL, [FacturacionAuto] BOOLEAN DEFAULT false NOT NULL, [CodigoAutorizacion] VARCHAR(10), [VigenciaCodigoAutorizacion] TIMESTAMP, [IvaVigente] NUMERIC(100,2) DEFAULT 0.16, CONSTRAINT SYS_PK_11029 PRIMARY KEY ([NitEmpresa]) ); CREATE UNIQUE INDEX SYS_IDX_REGISTROSOFTWARE_CODIGOSGSS_11003 ON [RegistroSoftware] ([CodigoSGSS]); CREATE UNIQUE INDEX SYS_IDX_REGISTROSOFTWARE_MAXEMPRESASREGISTRADAS_11016 ON [RegistroSoftware] ([MaxEmpresasRegistradas]); CREATE UNIQUE INDEX SYS_IDX_SYS_PK_11029_11030 ON [RegistroSoftware] ([NitEmpresa]);
-- [seccion] definition
-- Drop table
-- DROP TABLE [seccion];
CREATE TABLE [seccion] ( [codigo] VARCHAR(50) NOT NULL, [descripcion] VARCHAR(50) NOT NULL, CONSTRAINT SYS_PK_11051 PRIMARY KEY ([codigo]) ); CREATE UNIQUE INDEX SYS_IDX_SYS_PK_11051_11052 ON [seccion] ([codigo]);
-- [Sedes] definition
-- Drop table
-- DROP TABLE [Sedes];
CREATE TABLE [Sedes] ( [CodigoSede] VARCHAR(2) NOT NULL, [NombreSede] VARCHAR(50), [DireccionSede] VARCHAR(50), [TelefonoSede] VARCHAR(20), CONSTRAINT SYS_PK_11058 PRIMARY KEY ([CodigoSede]) ); CREATE UNIQUE INDEX SYS_IDX_SYS_PK_11058_11059 ON [Sedes] ([CodigoSede]);
-- [tarjeta de credito] definition
-- Drop table
-- DROP TABLE [tarjeta de credito];
CREATE TABLE [tarjeta de credito] ( [codigo] INTEGER NOT NULL, [descripcion] VARCHAR(20) NOT NULL, CONSTRAINT SYS_PK_11063 PRIMARY KEY ([codigo]) ); CREATE UNIQUE INDEX SYS_IDX_SYS_PK_11063_11064 ON [tarjeta de credito] ([codigo]);
-- [Tipo Codigo Alterno] definition
-- Drop table
-- DROP TABLE [Tipo Codigo Alterno];
CREATE TABLE [Tipo Codigo Alterno] ( [codigo] VARCHAR(3) NOT NULL, [descripcion] VARCHAR(20) NOT NULL, CONSTRAINT SYS_PK_11069 PRIMARY KEY ([codigo]) ); CREATE UNIQUE INDEX SYS_IDX_SYS_PK_11069_11070 ON [Tipo Codigo Alterno] ([codigo]);
-- [tipo muestra] definition
-- Drop table
-- DROP TABLE [tipo muestra];
CREATE TABLE [tipo muestra] ( [tipo] VARCHAR(5) NOT NULL, [descripcion] VARCHAR(20) NOT NULL, CONSTRAINT SYS_PK_11076 PRIMARY KEY ([tipo]) ); CREATE UNIQUE INDEX SYS_IDX_SYS_PK_11076_11077 ON [tipo muestra] ([tipo]);
-- [tipo tarifa] definition
-- Drop table
-- DROP TABLE [tipo tarifa];
CREATE TABLE [tipo tarifa] ( [codigo] VARCHAR(15) NOT NULL, [descripcion] VARCHAR(50) NOT NULL, CONSTRAINT SYS_PK_11083 PRIMARY KEY ([codigo]) ); CREATE UNIQUE INDEX SYS_IDX_SYS_PK_11083_11084 ON [tipo tarifa] ([codigo]);
-- [TipoAfiliado] definition
-- Drop table
-- DROP TABLE [TipoAfiliado];
CREATE TABLE [TipoAfiliado] ( [codigo] VARCHAR(1) NOT NULL, [nombre] VARCHAR(50) NOT NULL, CONSTRAINT SYS_PK_11090 PRIMARY KEY ([codigo]) ); CREATE UNIQUE INDEX SYS_IDX_SYS_PK_11090_11091 ON [TipoAfiliado] ([codigo]);
-- [TipoIdentificacion] definition
-- Drop table
-- DROP TABLE [TipoIdentificacion];
CREATE TABLE [TipoIdentificacion] ( [codigo] VARCHAR(3) NOT NULL, [nombre] VARCHAR(50) NOT NULL, CONSTRAINT SYS_PK_11097 PRIMARY KEY ([codigo]) ); CREATE UNIQUE INDEX SYS_IDX_SYS_PK_11097_11098 ON [TipoIdentificacion] ([codigo]);
-- [TipoProcedimiento] definition
-- Drop table
-- DROP TABLE [TipoProcedimiento];
CREATE TABLE [TipoProcedimiento] ( [codigo] VARCHAR(1) NOT NULL, [nombre] VARCHAR(50) NOT NULL, CONSTRAINT SYS_PK_11104 PRIMARY KEY ([codigo]) ); CREATE UNIQUE INDEX SYS_IDX_SYS_PK_11104_11105 ON [TipoProcedimiento] ([codigo]);
-- [TipoUsuario] definition
-- Drop table
-- DROP TABLE [TipoUsuario];
CREATE TABLE [TipoUsuario] ( [codigo] VARCHAR(1) NOT NULL, [nombre] VARCHAR(50) NOT NULL, CONSTRAINT SYS_PK_11111 PRIMARY KEY ([codigo]) ); CREATE UNIQUE INDEX SYS_IDX_SYS_PK_11111_11112 ON [TipoUsuario] ([codigo]);
-- [unidad] definition
-- Drop table
-- DROP TABLE [unidad];
CREATE TABLE [unidad] ( [codigo] VARCHAR(50) NOT NULL, [descripcion] VARCHAR(20) NOT NULL, CONSTRAINT SYS_PK_11118 PRIMARY KEY ([codigo]) ); CREATE UNIQUE INDEX SYS_IDX_SYS_PK_11118_11119 ON [unidad] ([codigo]);
-- [ZonaResidencia] definition
-- Drop table
-- DROP TABLE [ZonaResidencia];
CREATE TABLE [ZonaResidencia] ( [codigo] VARCHAR(1) NOT NULL, [nombre] VARCHAR(50) NOT NULL, CONSTRAINT SYS_PK_11125 PRIMARY KEY ([codigo]) ); CREATE UNIQUE INDEX SYS_IDX_SYS_PK_11125_11126 ON [ZonaResidencia] ([codigo]);
-- [abonos] definition
-- Drop table
-- DROP TABLE [abonos];
CREATE TABLE [abonos] ( [consecutivo] INTEGER, [NumReciboCaja] VARCHAR(20), [numero de orden] INTEGER, [forma de pago] INTEGER, [fecha de pago] TIMESTAMP, [valor abonado] INTEGER, [documento soporte] VARCHAR(50), [tarjeta de credito] INTEGER, [banco] SMALLINT, [UsuarioDigitacion] VARCHAR(50), [FechaDigitacion] TIMESTAMP, [UsuarioLastUpdate] VARCHAR(50), [FechaLastUpdate] TIMESTAMP, [HoraDigitacion] TIMESTAMP, CONSTRAINT ABONOS_REFERENCE3 FOREIGN KEY ([banco]) REFERENCES banco ON UPDATE CASCADE ); CREATE INDEX SYS_IDX_ABONOS_REFERENCE3_11421 ON [abonos] ([banco]);
-- [analisis] definition
-- Drop table
-- DROP TABLE [analisis];
CREATE TABLE [analisis] ( [consecutivo] INTEGER NOT NULL, [codigo examen] VARCHAR(10), [especimen] VARCHAR(20), [descripcion] VARCHAR(50) NOT NULL, [seccion] VARCHAR(50) NOT NULL, [CodigoSGSS] VARCHAR(10), [AutorizAdic] BOOLEAN DEFAULT false, [DiasMontaje] VARCHAR(30) DEFAULT LU a VI, [UsuarioDigitacion] VARCHAR(50), [FechaDigitacion] TIMESTAMP DEFAULT Date(), [UsuarioLastUpdate] VARCHAR(50), [FechaLastUpdate] TIMESTAMP, CONSTRAINT SYS_PK_10859 PRIMARY KEY ([consecutivo]), CONSTRAINT ANALISIS_SECCIONANALISIS FOREIGN KEY ([seccion]) REFERENCES seccion ON UPDATE CASCADE ); CREATE UNIQUE INDEX SYS_IDX_ANALISIS_DESCRIPCION_10853 ON [analisis] ([descripcion]); CREATE INDEX SYS_IDX_ANALISIS_SECCIONANALISIS_11145 ON [analisis] ([seccion]); CREATE UNIQUE INDEX SYS_IDX_SYS_PK_10859_10860 ON [analisis] ([consecutivo]);
-- [Codigo Analisis x Empresa] definition
-- Drop table
-- DROP TABLE [Codigo Analisis x Empresa];
CREATE TABLE [Codigo Analisis x Empresa] ( [tipo codigo alterno] VARCHAR(3) NOT NULL, [analisis] INTEGER NOT NULL, [codigo alterno] VARCHAR(10) NOT NULL, CONSTRAINT SYS_PK_10901 PRIMARY KEY ([tipo codigo alterno],[analisis]), CONSTRAINT [CODIGO ANALISIS X EMPRESA_ANALISISCODIGO ANALISIS X EMPRESA] FOREIGN KEY ([analisis]) REFERENCES analisis, CONSTRAINT [CODIGO ANALISIS X EMPRESA_{9D7824A2-FFE5-4A24-9A33-2B726072C0B7}] FOREIGN KEY ([tipo codigo alterno]) REFERENCES Tipo Codigo Alterno ON DELETE CASCADE ON UPDATE CASCADE ); CREATE INDEX [SYS_IDX_CODIGO ANALISIS X EMPRESA_ANALISISCODIGO ANALISIS X EMPRESA_11164] ON [Codigo Analisis x Empresa] ([analisis]); CREATE INDEX [SYS_IDX_CODIGO ANALISIS X EMPRESA_{9D7824A2-FFE5-4A24-9A33-2B726072C0B7}_11154] ON [Codigo Analisis x Empresa] ([tipo codigo alterno]); CREATE UNIQUE INDEX SYS_IDX_SYS_PK_10901_10902 ON [Codigo Analisis x Empresa] ([tipo codigo alterno],[analisis]);
-- [costo analisis] definition
-- Drop table
-- DROP TABLE [costo analisis];
CREATE TABLE [costo analisis] ( [tipo tarifa] VARCHAR(15) NOT NULL, [analisis] INTEGER DEFAULT 0 NOT NULL, [costo] DECIMAL(100,4) NOT NULL, CONSTRAINT SYS_PK_10917 PRIMARY KEY ([tipo tarifa],[analisis]), CONSTRAINT [COSTO ANALISIS_ANALISISCOSTO ANALISIS] FOREIGN KEY ([analisis]) REFERENCES analisis, CONSTRAINT [COSTO ANALISIS_REFERENCE13] FOREIGN KEY ([tipo tarifa]) REFERENCES tipo tarifa ON UPDATE CASCADE ); CREATE INDEX [SYS_IDX_COSTO ANALISIS_ANALISISCOSTO ANALISIS_11174] ON [costo analisis] ([analisis]); CREATE INDEX [SYS_IDX_COSTO ANALISIS_REFERENCE13_11182] ON [costo analisis] ([tipo tarifa]); CREATE UNIQUE INDEX SYS_IDX_SYS_PK_10917_10918 ON [costo analisis] ([tipo tarifa],[analisis]);
-- [detalle analisis] definition
-- Drop table
-- DROP TABLE [detalle analisis];
CREATE TABLE [detalle analisis] ( [consecutivo] INTEGER NOT NULL, [analisis] INTEGER NOT NULL, [descripcion] VARCHAR(50) NOT NULL, [unidad] VARCHAR(50), [orden de presentacion] SMALLINT NOT NULL, [normal de referencia] VARCHAR(255), [Es titulo ?] BOOLEAN DEFAULT false, [grafica] BOOLEAN, [RangoMinimo] NUMERIC(100,7), [RangoMaximo] NUMERIC(100,7), [UsuarioDigitacion] VARCHAR(50), [FechaDigitacion] TIMESTAMP DEFAULT date(), [UsuarioLastUpdate] VARCHAR(50), [FechaLastUpdate] TIMESTAMP, CONSTRAINT SYS_PK_10923 PRIMARY KEY ([consecutivo]), CONSTRAINT [DETALLE ANALISIS_ANALISISDETALLE ANALISIS] FOREIGN KEY ([analisis]) REFERENCES analisis ON DELETE CASCADE ); CREATE INDEX [DETALLE ANALISIS_ES TITULO ?] ON [detalle analisis] ([Es titulo ?]); CREATE INDEX [DETALLE ANALISIS_ORDEN DE PRESENTACION] ON [detalle analisis] ([orden de presentacion]); CREATE INDEX [SYS_IDX_DETALLE ANALISIS_ANALISISDETALLE ANALISIS_11190] ON [detalle analisis] ([analisis]); CREATE UNIQUE INDEX SYS_IDX_SYS_PK_10923_10924 ON [detalle analisis] ([consecutivo]);
-- [diagnostico] definition
-- Drop table
-- DROP TABLE [diagnostico];
CREATE TABLE [diagnostico] ( [consecutivo] INTEGER, [respuesta] VARCHAR(16777216), [analisis por orden] INTEGER DEFAULT 0 NOT NULL, [pregunta por analisis] INTEGER DEFAULT 0 NOT NULL, [chequeo] VARCHAR(2) DEFAULT false, [UsuarioDigitacion] VARCHAR(50), [FechaDigitacion] TIMESTAMP, [UsuarioLastUpdate] VARCHAR(50), [FechaLastUpdate] TIMESTAMP, [HoraDigitacion] TIMESTAMP DEFAULT Now(), CONSTRAINT [DIAGNOSTICO_DETALLE ANALISISDIAGNOSTICO] FOREIGN KEY ([pregunta por analisis]) REFERENCES detalle analisis ON DELETE CASCADE ); CREATE INDEX [DIAGNOSTICO_ANALISIS POR ORDEN] ON [diagnostico] ([analisis por orden]); CREATE INDEX [DIAGNOSTICO_FECHA DE REGISTRO] ON [diagnostico] ([FechaDigitacion]); CREATE INDEX [SYS_IDX_DIAGNOSTICO_DETALLE ANALISISDIAGNOSTICO_11202] ON [diagnostico] ([pregunta por analisis]);
-- [lista de valores] definition
-- Drop table
-- DROP TABLE [lista de valores];
CREATE TABLE [lista de valores] ( [consecutivo] INTEGER NOT NULL, [pregunta por analisis] INTEGER DEFAULT 0, [valor] VARCHAR(50), CONSTRAINT SYS_PK_10961 PRIMARY KEY ([consecutivo]), CONSTRAINT [LISTA DE VALORES_REFERENCE18] FOREIGN KEY ([pregunta por analisis]) REFERENCES detalle analisis ON DELETE CASCADE ); CREATE INDEX [SYS_IDX_LISTA DE VALORES_REFERENCE18_11211] ON [lista de valores] ([pregunta por analisis]); CREATE UNIQUE INDEX SYS_IDX_SYS_PK_10961_10962 ON [lista de valores] ([consecutivo]);
-- [muestra x orden] definition
-- Drop table
-- DROP TABLE [muestra x orden];
CREATE TABLE [muestra x orden] ( [consecutivo] INTEGER NOT NULL, [tipo] VARCHAR(5) NOT NULL, [fecha tomada] TIMESTAMP DEFAULT Date() NOT NULL, [numero de orden] INTEGER NOT NULL, [observaciones] VARCHAR(80), CONSTRAINT SYS_PK_10966 PRIMARY KEY ([consecutivo]), CONSTRAINT [MUESTRA X ORDEN_REFERENCE8] FOREIGN KEY ([tipo]) REFERENCES tipo muestra ON UPDATE CASCADE ); CREATE INDEX [SYS_IDX_MUESTRA X ORDEN_REFERENCE8_11218] ON [muestra x orden] ([tipo]); CREATE UNIQUE INDEX SYS_IDX_SYS_PK_10966_10967 ON [muestra x orden] ([consecutivo]);
-- [muestras x analisis] definition
-- Drop table
-- DROP TABLE [muestras x analisis];
CREATE TABLE [muestras x analisis] ( [consecutivo] INTEGER NOT NULL, [analisis] INTEGER NOT NULL, [descripcion] VARCHAR(20) NOT NULL, [tipo de muestra] VARCHAR(5) NOT NULL, CONSTRAINT SYS_PK_10974 PRIMARY KEY ([consecutivo]), CONSTRAINT [MUESTRAS X ANALISIS_ANALISISMUESTRAS X ANALISIS] FOREIGN KEY ([analisis]) REFERENCES analisis, CONSTRAINT [MUESTRAS X ANALISIS_REFERENCE11] FOREIGN KEY ([tipo de muestra]) REFERENCES tipo muestra ON UPDATE CASCADE ); CREATE INDEX [SYS_IDX_MUESTRAS X ANALISIS_ANALISISMUESTRAS X ANALISIS_11228] ON [muestras x analisis] ([analisis]); CREATE INDEX [SYS_IDX_MUESTRAS X ANALISIS_REFERENCE11_11238] ON [muestras x analisis] ([tipo de muestra]); CREATE UNIQUE INDEX SYS_IDX_SYS_PK_10974_10975 ON [muestras x analisis] ([consecutivo]);
-- [orden] definition
-- Drop table
-- DROP TABLE [orden];
CREATE TABLE [orden] ( [consecutivo] INTEGER, [numero de la orden] INTEGER, [paciente] INTEGER NOT NULL, [fecha] TIMESTAMP DEFAULT Date() NOT NULL, [cancelada] BOOLEAN DEFAULT false, [empresa a cobrar] INTEGER DEFAULT 0, [tipo tarifa] VARCHAR(15) NOT NULL, [valor a cobrar] INTEGER DEFAULT 0 NOT NULL, [otros conceptos] INTEGER DEFAULT 0, [DctoGlobal] INTEGER DEFAULT 0, [descuento] INTEGER DEFAULT 0, [VlrCopago] INTEGER DEFAULT 0, [VlrUsuario] INTEGER DEFAULT 0, [doctor] VARCHAR(50), [Auxiliar] VARCHAR(50), [observaciones] VARCHAR(16777216), [anulada] BOOLEAN DEFAULT false, [atendido por] VARCHAR(50), [voucher] VARCHAR(50), [NumPoliza] VARCHAR(20), [CodigoSede] VARCHAR(2) DEFAULT N, [NumAutorizAdic] VARCHAR(15), [TxtAutorizAdic] VARCHAR(50), [UsuarioDigitacion] VARCHAR(50), [FechaDigitacion] TIMESTAMP DEFAULT date(), [UsuarioLastUpdate] VARCHAR(50), [FechaLastUpdate] TIMESTAMP, [HoraDigitacion] TIMESTAMP DEFAULT Now(), CONSTRAINT ORDEN_REFERENCE12 FOREIGN KEY ([empresa a cobrar]) REFERENCES empresa, CONSTRAINT ORDEN_REFERENCE16 FOREIGN KEY ([paciente]) REFERENCES paciente ON UPDATE CASCADE ); CREATE INDEX ORDEN_CODIGOSEDE ON [orden] ([CodigoSede]); CREATE INDEX ORDEN_NUMAUTORIZADIC ON [orden] ([NumAutorizAdic]); CREATE UNIQUE INDEX [SYS_IDX_ORDEN_NUMERO DE LA ORDEN_10987] ON [orden] ([numero de la orden]); CREATE INDEX SYS_IDX_ORDEN_REFERENCE12_11248 ON [orden] ([empresa a cobrar]); CREATE INDEX SYS_IDX_ORDEN_REFERENCE16_11259 ON [orden] ([paciente]);
-- [ReglaCopago] definition
-- Drop table
-- DROP TABLE [ReglaCopago];
CREATE TABLE [ReglaCopago] ( [Consecutivo] INTEGER NOT NULL, [FkEmpresa] INTEGER DEFAULT 0, [MinExam] SMALLINT DEFAULT 1 NOT NULL, [MaxExam] SMALLINT DEFAULT 99 NOT NULL, [TrfCopago] INTEGER NOT NULL, CONSTRAINT SYS_PK_11043 PRIMARY KEY ([Consecutivo]), CONSTRAINT REGLACOPAGO_EMPRESAREGLACOPAGO FOREIGN KEY ([FkEmpresa]) REFERENCES empresa ON DELETE CASCADE ); CREATE INDEX SYS_IDX_REGLACOPAGO_EMPRESAREGLACOPAGO_11270 ON [ReglaCopago] ([FkEmpresa]); CREATE UNIQUE INDEX SYS_IDX_SYS_PK_11043_11044 ON [ReglaCopago] ([Consecutivo]);