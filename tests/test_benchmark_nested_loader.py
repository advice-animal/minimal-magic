"""Benchmark a deeply nested shape, in contrast to test_benchmark_loader's flat
arrays: a subset of Envoy's bootstrap config
(https://www.envoyproxy.io/docs/envoy/latest/api-v3/config/bootstrap/v3/bootstrap.proto),
chosen because real Envoy configs nest listener -> filter_chain -> filter ->
http_connection_manager -> route_config -> virtual_host -> route eight levels
deep, with a handful of fields at each level rather than one big flat list.
"""
import dataclasses
import json

import pytest

from minimal_magic import load, ParseError


@dataclasses.dataclass
class SocketAddress:
    address: str
    port_value: int


@dataclasses.dataclass
class Address:
    socket_address: SocketAddress


@dataclasses.dataclass
class RouteMatch:
    prefix: str


@dataclasses.dataclass
class RouteAction:
    cluster: str
    timeout: str | None = None


@dataclasses.dataclass
class Route:
    match: RouteMatch
    route: RouteAction


@dataclasses.dataclass
class VirtualHost:
    name: str
    domains: list[str]
    routes: list[Route]


@dataclasses.dataclass
class RouteConfig:
    name: str
    virtual_hosts: list[VirtualHost]


@dataclasses.dataclass
class HttpFilter:
    name: str


@dataclasses.dataclass
class HttpConnectionManager:
    stat_prefix: str
    route_config: RouteConfig
    http_filters: list[HttpFilter]


@dataclasses.dataclass
class Filter:
    name: str
    typed_config: HttpConnectionManager


@dataclasses.dataclass
class FilterChain:
    filters: list[Filter]


@dataclasses.dataclass
class Listener:
    name: str
    address: Address
    filter_chains: list[FilterChain]


@dataclasses.dataclass
class HealthCheckConfig:
    port_value: int


@dataclasses.dataclass
class Endpoint:
    address: Address
    health_check_config: HealthCheckConfig | None = None


@dataclasses.dataclass
class LbEndpoint:
    endpoint: Endpoint


@dataclasses.dataclass
class LocalityLbEndpoints:
    lb_endpoints: list[LbEndpoint]


@dataclasses.dataclass
class ClusterLoadAssignment:
    cluster_name: str
    endpoints: list[LocalityLbEndpoints]


@dataclasses.dataclass
class Cluster:
    name: str
    connect_timeout: str
    type: str
    lb_policy: str
    load_assignment: ClusterLoadAssignment


@dataclasses.dataclass
class StaticResources:
    listeners: list[Listener]
    clusters: list[Cluster]


@dataclasses.dataclass
class Node:
    id: str
    cluster: str


@dataclasses.dataclass
class Admin:
    address: Address


@dataclasses.dataclass
class Bootstrap:
    node: Node
    static_resources: StaticResources
    admin: Admin


def make_listener(i: int) -> dict:
    return {
        "name": f"listener_{i}",
        "address": {"socket_address": {"address": "0.0.0.0", "port_value": 10000 + i}},
        "filter_chains": [
            {
                "filters": [
                    {
                        "name": "envoy.filters.network.http_connection_manager",
                        "typed_config": {
                            "stat_prefix": f"ingress_{i}",
                            "route_config": {
                                "name": f"local_route_{i}",
                                "virtual_hosts": [
                                    {
                                        "name": f"backend_{i}",
                                        "domains": ["*"],
                                        "routes": [
                                            {
                                                "match": {"prefix": "/"},
                                                "route": {"cluster": f"service_{i}", "timeout": "5s"},
                                            },
                                            {
                                                "match": {"prefix": "/health"},
                                                "route": {"cluster": f"service_{i}", "timeout": None},
                                            },
                                        ],
                                    }
                                ],
                            },
                            "http_filters": [{"name": "envoy.filters.http.router"}],
                        },
                    }
                ]
            }
        ],
    }


def make_cluster(i: int) -> dict:
    return {
        "name": f"service_{i}",
        "connect_timeout": "0.25s",
        "type": "STRICT_DNS",
        "lb_policy": "ROUND_ROBIN",
        "load_assignment": {
            "cluster_name": f"service_{i}",
            "endpoints": [
                {
                    "lb_endpoints": [
                        {
                            "endpoint": {
                                "address": {
                                    "socket_address": {"address": f"10.0.{i % 256}.{n}", "port_value": 8080}
                                },
                                "health_check_config": {"port_value": 8081} if n == 0 else None,
                            }
                        }
                        for n in range(3)
                    ]
                }
            ],
        },
    }


def make_bootstrap(n: int) -> dict:
    return {
        "node": {"id": "bench-node", "cluster": "bench-cluster"},
        "static_resources": {
            "listeners": [make_listener(i) for i in range(n)],
            "clusters": [make_cluster(i) for i in range(n)],
        },
        "admin": {"address": {"socket_address": {"address": "127.0.0.1", "port_value": 9901}}},
    }


def test_benchmark_nested_envoy_config_load(benchmark, tmp_path):
    n = 300
    f = tmp_path / "envoy-bootstrap.json"
    f.write_text(json.dumps(make_bootstrap(n)))

    def run():
        return load(f, type=Bootstrap)

    result = benchmark.pedantic(run, rounds=5, iterations=1)
    assert len(result.static_resources.listeners) == n
    assert len(result.static_resources.clusters) == n
    assert result.static_resources.clusters[0].load_assignment.endpoints[0].lb_endpoints[0].endpoint.health_check_config.port_value == 8081
    assert result.static_resources.clusters[0].load_assignment.endpoints[0].lb_endpoints[1].endpoint.health_check_config is None


def test_benchmark_nested_envoy_config_load_validation_failure(benchmark, tmp_path):
    # Same document as test_benchmark_nested_envoy_config_load, but one
    # deeply-nested value is wrong (a cluster's port_value, several levels
    # into the last cluster). A clean load never builds a source map; this
    # is the cost of reporting a location once one does, on a deeply nested
    # document rather than the flat one in test_benchmark_loader.py.
    n = 300
    bootstrap = make_bootstrap(n)
    bad_endpoint = bootstrap["static_resources"]["clusters"][-1]["load_assignment"]["endpoints"][0]["lb_endpoints"][0]
    bad_endpoint["endpoint"]["address"]["socket_address"]["port_value"] = "not-an-int"
    f = tmp_path / "envoy-bootstrap-invalid.json"
    f.write_text(json.dumps(bootstrap))

    def run():
        with pytest.raises(ParseError) as exc_info:
            load(f, type=Bootstrap)
        return exc_info.value

    result = benchmark.pedantic(run, rounds=5, iterations=1)
    assert "Expected `int`" in str(result)
