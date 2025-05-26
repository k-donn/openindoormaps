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


class LevelZeroWayHandler(osmium.SimpleHandler):
    def __init__(self):
        super().__init__()
        self.way_nodes = {}  # way_id -> list of node_ids
        self.area_ways = set()  # way_ids with room:area or room:corridor
        # way_ids -> LineString with room:area or room:corridor
        self.area_geojsons = defaultdict()
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

        if level not in {"0", "0.0"}:
            return  # Skip non-ground level/multi-level ways
        
        if indoor_type == "level":
            return

        node_ids = [n.ref for n in w.nodes]
        if not node_ids:
            return

        way_id = w.id
        self.way_nodes[way_id] = node_ids

        geom_str = None

        if room_type == "corridor":
            self.area_ways.add(way_id)
            if w.is_closed():
                # For closed ways, attempt to create a Polygon.
                # Osmium's create_polygon is somewhat strict (e.g., expects area tags or no conflicting tags).
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
                self.area_geojsons[way_id] = feature

        else:
            self.dest_ways.add(way_id)

        for node_id in node_ids:
            self.node_to_ways[node_id].add(way_id)

        # Store the centroid of the way as the way's representative location
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
        lat = getattr(handler, '_way_locations', {}
                      ).get(way_id, (None, None))[0]
        lon = getattr(handler, '_way_locations', {}
                      ).get(way_id, (None, None))[1]
        G.add_node(
            way_id,
            is_room=way_id in handler.area_ways,
            lat=lat,
            lon=lon
        )

    for area_way_id in handler.area_ways:
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
        lat = getattr(handler, '_way_locations', {}
                      ).get(dest_way_id, (None, None))[0]
        lon = getattr(handler, '_way_locations', {}
                      ).get(dest_way_id, (None, None))[1]
        H.add_node(
            str(dest_way_id),
            lat=lat,
            lon=lon
        )

    for area_way_id in handler.area_ways:
        centerline = handler.area_geojsons[area_way_id]
        # If the centerline is a MultiLineString, flatten to a list of segments
        line = centerline.geometry["coordinates"]

        # Build a tree graph from the centerline lines
        node_lookup = {}
        node_idx = 0
        for segment in line:
            for node in segment:
                if (node[0], node[1]) not in node_lookup:
                    node_name = f"{area_way_id}_{node_idx}"
                    H.add_node(node_name, lat=node[1], lon=node[0])
                    node_lookup[(node[0], node[1])] = node_name
                    node_idx += 1

        for segment in line:
            u = node_lookup[tuple(segment[0])]
            v = node_lookup[tuple(segment[1])]
            if u == v:
                continue
            H.add_edge(u, v)

    for possible_tree in nx.connected_components(H):
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
            if nbh_data["is_room"]:
                # connect nearest tree node to nearest of other tree
                pass
            else:
                # Find the nearest node in T to the centroid of the neighbor way
                neighbor_lat = nbh_data.get('lat')
                neighbor_lon = nbh_data.get('lon')
                if neighbor_lat is None or neighbor_lon is None:
                    continue
                min_dist = float('inf')
                nearest_node = None
                for node, data in T.nodes(data=True):
                    d = (data['lat'] - neighbor_lat) ** 2 + \
                        (data['lon'] - neighbor_lon) ** 2
                    if d < min_dist:
                        min_dist = d
                        nearest_node = node
                if nearest_node is not None:
                    H.add_edge(nearest_node, str(neighbor))

    return H


def visualize_graph(G):
    pos = nx.spring_layout(G, seed=42)

    # Separate room vs non-room nodes
    room_nodes = [n for n, d in G.nodes(data=True) if d.get('is_room', False)]
    non_room_nodes = [n for n in G.nodes if n not in room_nodes]

    plt.figure(figsize=(12, 8))

    nx.draw_networkx_nodes(G, pos, nodelist=non_room_nodes,
                           node_color='skyblue', node_size=300, label="Non-room ways")
    nx.draw_networkx_nodes(G, pos, nodelist=room_nodes, node_color='red',
                           node_size=300, label="Room:area/corridor ways")

    nx.draw_networkx_edges(G, pos, edge_color='gray')
    nx.draw_networkx_labels(G, pos, font_size=8)

    plt.title("Way Connection Graph via room:area / room:corridor (Level 0)")
    plt.legend()
    plt.axis('off')
    plt.tight_layout()
    plt.show()

def visualize_geograph(G):
    pos = {n: (d['lon'], d['lat']) for n, d in G.nodes(data=True) if d.get('lat') is not None and d.get('lon') is not None}

    # Separate room vs non-room nodes
    room_nodes = [n for n, d in G.nodes(data=True) if d.get('is_room', False)]
    non_room_nodes = [n for n in G.nodes if n not in room_nodes]

    plt.figure(figsize=(12, 8))

    nx.draw_networkx_nodes(G, pos, nodelist=non_room_nodes,
                           node_color='skyblue', node_size=300, label="Non-room ways")
    nx.draw_networkx_nodes(G, pos, nodelist=room_nodes, node_color='red',
                           node_size=300, label="Room:area/corridor ways")

    nx.draw_networkx_edges(G, pos, edge_color='gray')
    nx.draw_networkx_labels(G, pos, font_size=8)

    plt.title("Way Connection Graph via room:area / room:corridor (Level 0)")
    plt.legend()
    plt.axis('off')
    plt.tight_layout()
    plt.show()


def main(osm_file, route_file, visualize, visualize_geo):
    handler = LevelZeroWayHandler()
    handler.apply_file(osm_file, locations=True)

    graph = build_graph(handler)

    geo_graph = embed_graph(graph, handler)

    if visualize:
        visualize_graph(graph)

    if visualize_geo:
        visualize_geograph(geo_graph)

    features = []
    for u, v in graph.edges():
        u_lat = graph.nodes[u]['lat']
        u_lon = graph.nodes[u]['lon']
        v_lat = graph.nodes[v]['lat']
        v_lon = graph.nodes[v]['lon']
        if None in (u_lat, u_lon, v_lat, v_lon):
            continue  # skip edges with missing coordinates
        line = geojson.LineString([(u_lon, u_lat), (v_lon, v_lat)])
        feature = geojson.Feature(
            geometry=line,
            properties={
                "from": u,
                "to": v,
                "from_is_room": graph.nodes[u]['is_room'],
                "to_is_room": graph.nodes[v]['is_room']
            }
        )
        features.append(feature)

    feature_collection = geojson.FeatureCollection(features)

    features = []
    for u, v in geo_graph.edges():
        u_lat = geo_graph.nodes[u]['lat']
        u_lon = geo_graph.nodes[u]['lon']
        v_lat = geo_graph.nodes[v]['lat']
        v_lon = geo_graph.nodes[v]['lon']
        if None in (u_lat, u_lon, v_lat, v_lon):
            continue  # skip edges with missing coordinates
        line = geojson.LineString([(u_lon, u_lat), (v_lon, v_lat)])
        feature = geojson.Feature(
            geometry=line,
            properties={
                "from": u,
                "to": v
            }
        )
        features.append(feature)

    feature_collection = geojson.FeatureCollection(features)

    with open(route_file, "w") as f:
        geojson.dump(feature_collection, f)

    print(
        f"Graph has {graph.number_of_nodes()} nodes and {graph.number_of_edges()} edges.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Process OSM file and generate graphs.")
    parser.add_argument("osm_file", help="Input path to the OSM file")
    parser.add_argument("route_file", help="Output path to the GeoJSON file")
    parser.add_argument("--visualize", action="store_true", help="Visualize the way connection graph")
    parser.add_argument("--visualize-geo", action="store_true", help="Visualize the geographic connection graph")
    args = parser.parse_args()

    main(args.osm_file, args.route_file, args.visualize, args.visualize_geo)
