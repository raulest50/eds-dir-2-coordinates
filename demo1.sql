

select distinct codigo_tipo_agente, tipo_agente from sbi_agentes;

select distinct subtipo_agente, codigo_subtipo_agente, tipo_agente from sbi_agentes;

select distinct descripcion_producto, codigo_producto from sbi_ordenes_pedidos;

select distinct bandera, codigo_bandera from sbi_agentes;

select distinct subtipo_agente from sbi_capacidad;


select distinct anio_ciclo, codigo_sicom_agente, capacidad_operativa, descripcion_producto
from sbi_capacidad
where codigo_sicom_agente = "633001"
limit 10;


select count(*) from sbi_capacidad;