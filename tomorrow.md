# Sesión siguiente

## Estado

**Tarea 1: HECHA**

- Repo cimientos: .gitignore, pytest.ini, requirements.txt
- Fixtures copiadas de salidas/agora_test
- Logger LogCentral integrado (enjambre.registro.obtener_log)
- Tests verdes

## Siguiente

Tarea 2: Intro al SDK — agentes dummy sin función aún.

## Bloqueos / le toca a Josem

**LogCentral vector.toml:** Para que LogCentral recoja los logs de enjambre, hay que añadir en `/data/logcentral/vector/vector.toml`:

1. Nuevo `[sources.enjambre]` con `include = ["/data/enjambre-explicador/logs/enjambre.log"]`
2. Nuevo `[transforms.parse_enjambre]` copiado de `parse_saxhero` pero con nombre `parse_enjambre`
3. Añadir `parse_enjambre` a los dos `inputs = [...]` que agregan todos los parse (buscar líneas que agreguen todos los parse)
4. Reiniciar Vector: `sudo systemctl restart vector`

Sin esto, `/data/enjambre-explicador/logs/enjambre.log` se crea pero no se indexa en LogCentral.
