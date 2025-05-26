import osmium
import geojson
import sys
import argparse
from shapely.geometry import Polygon
from shapely.affinity import scale

# Initialize the GeoJSON factory from Osmium. This is used to create GeoJSON geometry strings.
geojson_factory = osmium.geom.GeoJSONFactory()

# Flatten coordinates for Polygon or MultiPolygon
def flatten_coords(c):
    if isinstance(c[0][0], (float, int)):
        return c
    elif isinstance(c[0][0], (list, tuple)):
        return [pt for ring in c for pt in flatten_coords(ring)]
    else:
        return []

class LevelFeatureHandler(osmium.SimpleHandler):
    """
    Osmium handler to process OSM elements and convert those with a 'level' tag
    into GeoJSON features.
    """

    def __init__(self):
        super().__init__()
        self.features = []  # List to store geojson.Feature objects
        self.pois = []
        self.curr_poi_id = 0

    def way(self, w):
        """
        Process OSM ways.
        If a way has a 'level' tag, convert it to a GeoJSON LineString or Polygon feature.
        """
        if 'level' in w.tags:
            raw_props = {tag.k: tag.v for tag in w.tags}
            if "highway" in raw_props:
                if raw_props["highway"] == "elevator":
                    # TODO: handle elevators
                    return
            if int(raw_props["level"]) != 0:
                return
            props = {}
            props["level_id"] = int(raw_props["level"])
            props["area"] = 0
            props["show"] = True
            if "ref" in raw_props:
                props["ref"] = raw_props["ref"]
            if "indoor" in raw_props:
                if raw_props["indoor"] == "level":
                    props["feature_type"] = "corridor"
                elif raw_props["indoor"] == "room":
                    if "room" in raw_props:
                        if raw_props["room"] == "area" or raw_props["room"] == "corridor":
                            # TODO: integrate graph.py here
                            return
                        else:
                            props["feature_type"] = "unit"
                elif raw_props["indoor"] == "area":
                    # TODO: integrate graph.py here
                    return
                else:
                    # incorrectly tagged way
                    return
            geom_str = None
            # try:
            if w.is_closed():
                # For closed ways, attempt to create a Polygon.
                # Osmium's create_polygon is somewhat strict (e.g., expects area tags or no conflicting tags).
                try:
                    geom_str = geojson_factory.create_multipolygon(w)
                except:
                    # If polygon creation fails (e.g., not considered an area by osmium, or self-intersecting),
                    # fall back to creating a LineString for the closed loop.
                    geom_str = geojson_factory.create_linestring(w)
            else:
                # For open ways, create a LineString.
                geom_str = geojson_factory.create_linestring(w)
            try:
                if geom_str:
                    geom = geojson.loads(geom_str)
                    
                    if "feature_type" in props and props["feature_type"] == "unit":
                        coordinates = geom['coordinates']
                        polygon = Polygon(coordinates)
                        scaled_poly = scale(polygon, xfact=0.95, yfact=0.95, origin="centroid")
                        geom = geojson.loads(geojson.dumps(scaled_poly.__geo_interface__))
                        # make POI for each unit
                        poi_props = {
                            "id": self.curr_poi_id,
                            "name": f"Room {props["ref"]}" if "ref" in props else f"Room #{self.curr_poi_id}",
                            "type": raw_props["room"],
                            "floor": int(props["level_id"]),
                            "building_id": "17249577"
                        }

                        # Calculate centroid as average of all coordinates in the geometry
                        coords = geom["coordinates"]
                        
                        flat = flatten_coords(coords)
                        if flat:
                            avg_lon = sum(pt[0] for pt in flat) / len(flat)
                            avg_lat = sum(pt[1] for pt in flat) / len(flat)
                            poi_geom = geojson.Point((avg_lon, avg_lat))
                            poi_feature = geojson.Feature(
                                id=self.curr_poi_id,
                                geometry=poi_geom,
                                properties=poi_props
                            )
                            self.pois.append(poi_feature)
                            self.curr_poi_id += 1

                    feature = geojson.Feature(
                        id=w.id, geometry=geom, properties=props)
                    self.features.append(feature)
            except Exception as e:
                # This can happen if a linestring has too few nodes, etc.
                sys.stderr.write(
                    f"Warning: Skipping way {w.id} due to invalid geometry: {e}\n")
            except Exception as e:
                sys.stderr.write(
                    f"Warning: Skipping way {w.id} due to an unexpected error: {e}\n")


def main():
    """
    Main function to parse arguments, run the OSM processing, and write the GeoJSON output.
    """
    parser = argparse.ArgumentParser(
        description='Convert OSM elements with a "level" tag to GeoJSON.')
    parser.add_argument(
        'osm_file', help='Input OSM file (e.g., .osm, .osm.pbf)')
    parser.add_argument(
        'route_file', help='Input route file from graph.py')
    parser.add_argument(
        'geojson_file', help='Output GeoJSON file (e.g., building.json)')

    args = parser.parse_args()

    level_handler = LevelFeatureHandler()

    try:
        sys.stdout.write(f"Processing OSM file: {args.osm_file}...\n")
        level_handler.apply_file(args.osm_file, locations=True, idx='flex_mem')
    except FileNotFoundError:
        sys.stderr.write(f"Error: Input OSM file not found: {args.osm_file}\n")
        sys.exit(1)
    except Exception as e:  # Catch other osmium-related processing errors
        sys.stderr.write(f"Error processing OSM file: {e}\n")
        sys.exit(1)

    # Create a GeoJSON FeatureCollection from the collected features
    feature_collection = geojson.FeatureCollection(level_handler.features)
    poi_collection = geojson.FeatureCollection(level_handler.pois)

    indoor_routes = {}

    with open(args.route_file, "r") as f:
        indoor_routes = geojson.load(f)

    try:
        with open(args.geojson_file, 'w') as f:
            res = {
                "id": "17249577",
                "name": "Driftmier",
                "description": "UGA Driftmier Engineering Center",
                "address": "597 DW Brooks Dr, Athens, GA 30605",
                "location": {
                    "latitude": 33.938878,
                    "longitude": -83.375005
                },
                "indoor_map": feature_collection,
                "pois": poi_collection,
                "indoor_routes": indoor_routes
            }
            geojson.dump(res, f, indent=2)  # indent for pretty printing
        sys.stdout.write(
            f"Successfully wrote {len(level_handler.features)} features with 'level' tag to {args.geojson_file}\n")
    except IOError as e:
        sys.stderr.write(f"Error writing GeoJSON file: {e}\n")
        sys.exit(1)
    except Exception as e:
        sys.stderr.write(
            f"An unexpected error occurred while writing the GeoJSON file: {e}\n")
        sys.exit(1)


if __name__ == '__main__':
    main()
