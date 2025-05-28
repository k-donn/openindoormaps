import itertools
import osmium
import copy
import networkx as nx
import matplotlib.pyplot as plt
from collections import defaultdict
from shapely.geometry import Polygon
from centerline.geometry import Centerline
import geojson
import argparse

# Initialize the GeoJSON factory from Osmium. This is used to create GeoJSON geometry strings.
geojson_factory = osmium.geom.GeoJSONFactory()


class LevelWayHandler(osmium.SimpleHandler):
    def __init__(self, level_id):
        super().__init__()
        self.level_id = level_id
        self.way_nodes = {}  # way_id -> list of node_ids
        self.route_ways = set()  # way_ids with room:area or room:corridor
        self.vertical_ways = set()
        # way_ids -> LineString with room:area or room:corridor
        self.route_geojsons = defaultdict()
        self.dest_ways = set()  # all other way_ids
        self.node_to_ways = defaultdict(set)  # node_id -> set of way_ids
        self.node_locations = {}  # node_id -> (lat, lon)
        self._way_locations = {}  # way_id -> (lat, lon)

    def node(self, n):
        self.node_locations[n.id] = (n.location.lat, n.location.lon)

    def way(self, w):
        tags = {tag.k: tag.v for tag in w.tags}
        indoor_type = tags.get("indoor", None)
        level = tags.get("level", None)
        room_type = tags.get("room", None)

        if level is None:
            return
        else:
            if room_type == "elevator":
                min_level = int(level.split("-")[0])
                max_level = int(level.split("-")[1])
                if self.level_id < min_level or self.level_id > max_level:
                    return
            elif level != str(self.level_id):
                return

        if indoor_type == "level":
            return

        node_ids = [n.ref for n in w.nodes]
        if not node_ids:
            return

        way_id = w.id
        self.way_nodes[way_id] = node_ids

        geom_str = None

        if room_type == "corridor" or indoor_type == "area":
            self.route_ways.add(way_id)
            if w.is_closed():
                # For closed ways, attempt to create a Polygon.
                # Osmium"s create_polygon is somewhat strict (e.g., expects area tags or no conflicting tags).
                try:
                    geom_str = geojson_factory.create_multipolygon(w)
                except:
                    # If polygon creation fails (e.g., not considered an area by osmium, or self-intersecting),
                    # fall back to creating a LineString for the closed loop.
                    geom_str = geojson_factory.create_linestring(w)
                geom = geojson.loads(geom_str)
                coords = geom["coordinates"]
                polygon = Polygon(coords)
                centerline = Centerline(
                    polygon, interpolation_distance=0.00001)
                centerline_geom = geojson.loads(geojson.dumps(
                    centerline.geometry.__geo_interface__))
                feature = geojson.Feature(
                    geometry=centerline_geom, properties={"id": way_id})
                self.route_geojsons[way_id] = feature

        elif room_type == "elevator":
            self.vertical_ways.add(way_id)
        else:
            self.dest_ways.add(way_id)

        for node_id in node_ids:
            self.node_to_ways[node_id].add(way_id)

        # Store the centroid of the way as the way"s representative location
        coords = [self.node_locations.get(
            nid) for nid in node_ids if nid in self.node_locations]
        if coords:
            lat = sum(lat for lat, _ in coords) / len(coords)
            lon = sum(lon for _, lon in coords) / len(coords)
            self._way_locations[way_id] = (lat, lon)

    @property
    def way_locations(self):
        # Return a dict: way_id -> (lat, lon)
        return self._way_locations


def build_graph(handler):
    G = nx.Graph()

    for way_id in handler.way_nodes:
        # Try to get lat/lon from the handler (if available)
        lat = getattr(handler, "_way_locations", {}
                      ).get(way_id, (None, None))[0]
        lon = getattr(handler, "_way_locations", {}
                      ).get(way_id, (None, None))[1]
        G.add_node(
            way_id,
            is_routable=way_id in handler.route_ways or way_id in handler.vertical_ways,
            is_vertical=way_id in handler.vertical_ways,
            lat=lat,
            lon=lon,
            floor=handler.level_id
        )

    for area_way_id in handler.route_ways:
        shared_nodes = handler.way_nodes[area_way_id]
        connected_ways = set()

        for node_id in shared_nodes:
            connected_ways.update(handler.node_to_ways[node_id])

        connected_ways.discard(area_way_id)

        for way_a in connected_ways:
            G.add_edge(way_a, area_way_id)

    return G


def embed_graph(G, handler):
    H = nx.Graph()

    for dest_way_id in handler.dest_ways:
        # Try to get lat/lon from the handler (if available)
        lat = getattr(handler, "_way_locations", {}
                      ).get(dest_way_id, (None, None))[0]
        lon = getattr(handler, "_way_locations", {}
                      ).get(dest_way_id, (None, None))[1]
        H.add_node(
            str(dest_way_id),
            is_routable=False,
            is_vertical=False,
            lat=lat,
            lon=lon,
            floor=handler.level_id
        )

    for vertical_way_id in handler.vertical_ways:
        # Try to get lat/lon from the handler (if available)
        lat = getattr(handler, "_way_locations", {}
                      ).get(vertical_way_id, (None, None))[0]
        lon = getattr(handler, "_way_locations", {}
                      ).get(vertical_way_id, (None, None))[1]
        H.add_node(
            f"{vertical_way_id}_{handler.level_id}",
            is_routable=True,
            is_vertical=True,
            lat=lat,
            lon=lon,
            floor=handler.level_id
        )

    for area_way_id in handler.route_ways:
        centerline = handler.route_geojsons[area_way_id]
        # If the centerline is a MultiLineString, flatten to a list of segments
        line = centerline.geometry["coordinates"]

        # Build a tree graph from the centerline lines
        node_lookup = {}
        node_idx = 0
        for segment in line:
            for node in segment:
                if (node[0], node[1]) not in node_lookup:
                    node_name = f"{area_way_id}_{node_idx}"
                    H.add_node(
                        node_name, lat=node[1], lon=node[0], is_routable=True, is_vertical=False, floor=handler.level_id)
                    node_lookup[(node[0], node[1])] = node_name
                    node_idx += 1

        for segment in line:
            u = node_lookup[tuple(segment[0])]
            v = node_lookup[tuple(segment[1])]
            if u == v:
                continue
            H.add_edge(u, v)

    for possible_tree in nx.connected_components(H):
        # TODO: remove isolated verts
        T = H.subgraph(possible_tree)
        assert nx.is_tree(T)

    area_trees = copy.deepcopy(list(nx.connected_components(H)))
    for tree in area_trees:
        if len(tree) == 1:
            continue
        T = H.subgraph(tree)
        first_node = next(iter(T.nodes))
        area_way_id = first_node.split("_")[0]
        # all adjacent ways to this tree
        neighbors = G[int(area_way_id)]
        for neighbor in neighbors:
            nbh_data = G.nodes[neighbor]
            if nbh_data["is_routable"]:
                nbh_tree = None
                for poss_nbh in area_trees:
                    first_nbh = next(iter(poss_nbh))
                    if first_nbh.split("_")[0] == str(neighbor):
                        nbh_tree = poss_nbh
                if nbh_tree is not None:
                    nbh_T = H.subgraph(nbh_tree)
                    min_dist = float("inf")
                    closest_pair = (None, None)
                    for node1, data1 in T.nodes(data=True):
                        for node2, data2 in nbh_T.nodes(data=True):
                            d = (data1["lat"] - data2["lat"]) ** 2 + \
                                (data1["lon"] - data2["lon"]) ** 2
                            if d < min_dist:
                                min_dist = d
                                closest_pair = (node1, node2)
                    if closest_pair[0] is not None and closest_pair[1] is not None:
                        H.add_edge(closest_pair[0], closest_pair[1])
            else:
                # Find the nearest node in T to the centroid of the neighbor way
                neighbor_lat = nbh_data.get("lat")
                neighbor_lon = nbh_data.get("lon")
                if neighbor_lat is None or neighbor_lon is None:
                    continue
                min_dist = float("inf")
                nearest_node = None
                for node, data in T.nodes(data=True):
                    d = (data["lat"] - neighbor_lat) ** 2 + \
                        (data["lon"] - neighbor_lon) ** 2
                    if d < min_dist:
                        min_dist = d
                        nearest_node = node
                if nearest_node is not None:
                    H.add_edge(str(neighbor), nearest_node)

    return H


def visualize_graph(G, is_geograph):
    pos = None
    if is_geograph:
        pos = {n: (d["lon"], d["lat"]) for n, d in G.nodes(data=True)
               if d.get("lat") is not None and d.get("lon") is not None}
    else:
        pos = nx.spring_layout(G, seed=42)

    # Separate route vs non-route nodes
    route_nodes = [n for n, d in G.nodes(
        data=True) if d.get("is_routable", False) and not d.get("is_vertical", False)]
    non_route_nodes = [n for n, d in G.nodes(
        data=True) if not d.get("is_routable", False)]
    vertical_nodes = [n for n, d in G.nodes(
        data=True) if d.get("is_vertical", False)]

    plt.figure(figsize=(12, 8))

    nx.draw_networkx_nodes(G, pos, nodelist=non_route_nodes,
                           node_color="skyblue", node_size=300, label="Non-route ways")
    nx.draw_networkx_nodes(G, pos, nodelist=route_nodes, node_color="red",
                           node_size=300, label="Room:area/corridor ways")
    nx.draw_networkx_nodes(G, pos, nodelist=vertical_nodes, node_color="darkblue",
                           node_size=300, label="Vertical ways")

    nx.draw_networkx_edges(G, pos, edge_color="gray")
    nx.draw_networkx_labels(G, pos, font_size=8)

    plt.title("Way Connection Graph via room:area / room:corridor (Level 0)")
    plt.legend()
    plt.axis("off")
    plt.tight_layout()
    plt.show()

def combine_level_graphs(G1, G2):
    H = nx.Graph()
    H.add_nodes_from(G1.nodes(data=True))
    H.add_edges_from(G1.edges(data=True))
    H.add_nodes_from(G2.nodes(data=True))
    H.add_edges_from(G2.edges(data=True))

    vertical_nodes = [n for n, d in H.nodes(data=True) if d.get("is_vertical", False)]

    for u, v in itertools.combinations(vertical_nodes, 2):
        parent_u = u.split("_")[0]
        parent_v = v.split("_")[0]
        if parent_u == parent_v:
            H.add_edge(u,v)
    return H

def extract_graph_features(graph):
    features = []
    for u, v in graph.edges():
        u_lat = graph.nodes[u]["lat"]
        u_lon = graph.nodes[u]["lon"]
        v_lat = graph.nodes[v]["lat"]
        v_lon = graph.nodes[v]["lon"]
        u_floor = graph.nodes[u]["floor"]
        v_floor = graph.nodes[v]["floor"]
        if None in (u_lat, u_lon, v_lat, v_lon):
            continue  # skip edges with missing coordinates
        line = geojson.LineString([(u_lon, u_lat), (v_lon, v_lat)])
        feature = geojson.Feature(
            geometry=line,
            properties={
                "from": u,
                "to": v,
                "from_is_routable": graph.nodes[u]["is_routable"],
                "to_is_routable": graph.nodes[v]["is_routable"],
                "from_floor": u_floor,
                "to_floor": v_floor
            }
        )
        features.append(feature)
    return features


def main(osm_file, route_file, visualize, visualize_geo):
    handler_0 = LevelWayHandler(0)
    handler_1 = LevelWayHandler(1)
    handler_0.apply_file(osm_file, locations=True)
    handler_1.apply_file(osm_file, locations=True)

    graph_0 = build_graph(handler_0)
    graph_1 = build_graph(handler_1)

    geo_graph_0 = embed_graph(graph_0, handler_0)
    geo_graph_1 = embed_graph(graph_1, handler_1)

    if visualize:
        visualize_graph(graph_0)
        visualize_graph(graph_1)


    geo_graph = combine_level_graphs(geo_graph_0, geo_graph_1)

    if visualize_geo:
        visualize_graph(geo_graph, True)

    geo_features = extract_graph_features(geo_graph)

    geo_feature_collection = geojson.FeatureCollection(geo_features)

    with open(route_file, "w") as f:
        geojson.dump(geo_feature_collection, f)

    print(
        f"Geographic Graph has {geo_graph.number_of_nodes()} nodes and {geo_graph.number_of_edges()} edges.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Process OSM file and generate graphs.")
    parser.add_argument("osm_file", help="Input path to the OSM file")
    parser.add_argument("route_file", help="Output path to the GeoJSON file")
    parser.add_argument("--visualize", action="store_true",
                        help="Visualize the way connection graph")
    parser.add_argument("--visualize-geo", action="store_true",
                        help="Visualize the geographic connection graph")
    args = parser.parse_args()

    main(args.osm_file, args.route_file, args.visualize, args.visualize_geo)
