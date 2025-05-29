import Graph from "../pathfinding/graph";
import PathFinder from "../pathfinding/pathfinder";
import { MapLibreGlDirectionsConfiguration } from "../types";
import {
  IndoorDirectionsEvented,
  IndoorDirectionsRoutingEvent,
  IndoorDirectionsWaypointEvent,
} from "./events";
import {
  buildConfiguration,
  buildPoint,
  buildRouteLines,
  buildSnaplines,
} from "./utils";
import { POI } from "~/types/poi";
import useFloorStore from "~/stores/floor-store";

export default class IndoorDirections extends IndoorDirectionsEvented {
  declare protected readonly map: maplibregl.Map;
  private readonly pathFinder: PathFinder;

  protected readonly configuration: MapLibreGlDirectionsConfiguration;

  protected buildPoint = buildPoint;
  protected buildSnaplines = buildSnaplines;
  protected buildRouteLines = buildRouteLines;

  protected _waypoints: GeoJSON.Feature<GeoJSON.Point>[] = [];
  protected snappoints: GeoJSON.Feature<GeoJSON.Point>[] = [];
  protected routelines: GeoJSON.Feature<GeoJSON.LineString>[] = [];
  private coordMap: Map<string, Set<GeoJSON.Position[]>> = new Map();
  private graph: Graph = new Graph();

  constructor(
    map: maplibregl.Map,
    configuration?: Partial<MapLibreGlDirectionsConfiguration>,
  ) {
    super(map);
    this.map = map;

    this.configuration = buildConfiguration(configuration);
    this.pathFinder = new PathFinder();

    this.init();
  }

  protected init() {
    this.map.addSource(this.configuration.sourceName, {
      type: "geojson",
      data: {
        type: "FeatureCollection",
        features: [],
      },
    });

    this.configuration.layers.forEach((layer) => {
      this.map.addLayer(layer);
    });

    useFloorStore.subscribe((state) => {
      this.draw(state.currentFloor);
    });
  }

  protected get waypointsCoordinates(): [number, number][] {
    return this._waypoints.map((waypoint) => {
      return [
        waypoint.geometry.coordinates[0],
        waypoint.geometry.coordinates[1],
      ];
    });
  }

  protected get snappointsCoordinates(): [number, number][] {
    return this.snappoints.map((snappoint) => {
      return [
        snappoint.geometry.coordinates[0],
        snappoint.geometry.coordinates[1],
      ];
    });
  }

  public get routelinesCoordinates() {
    return this.routelines;
  }

  protected get snaplines() {
    return this.snappoints.length > 1
      ? this.buildSnaplines(this._waypoints, this.snappoints)
      : [];
  }

  private calculateDistance(
    coord1: GeoJSON.Position,
    coord2: GeoJSON.Position,
  ) {
    const [lon1, lat1] = coord1;
    const [lon2, lat2] = coord2;
    const R = 6371; // Earth's radius in kilometers
    const dLat = ((lat2 - lat1) * Math.PI) / 180;
    const dLon = ((lon2 - lon1) * Math.PI) / 180;
    const a =
      Math.sin(dLat / 2) * Math.sin(dLat / 2) +
      Math.cos((lat1 * Math.PI) / 180) *
        Math.cos((lat2 * Math.PI) / 180) *
        Math.sin(dLon / 2) *
        Math.sin(dLon / 2);
    const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
    return R * c;
  }

  private findNearestGraphPoint(
    point: GeoJSON.Position,
    coordMap: Map<string, Set<GeoJSON.Position[]>>,
    floor: number,
  ): GeoJSON.Position | null {
    let nearest: GeoJSON.Position | null = null;
    let minDistance = Infinity;

    // coordMap.forEach((_, coordStr) => {
    //   const coord = JSON.parse(coordStr);
    //   const distance = this.calculateDistance(point, coord);
    //   if (distance < minDistance) {
    //     minDistance = distance;
    //     nearest = coord;
    //   }
    // });

    this.graph
      .getVertices()
      .filter((vert) => this.graph.getVertexProperties(vert)?.floor === floor)
      .forEach((vert) => {
        const coord = JSON.parse(vert);
        const distance = this.calculateDistance(point, coord);
        if (distance < minDistance) {
          minDistance = distance;
          nearest = coord;
        }
      });

    return nearest;
  }

  private updateSnapPoints() {
    this.snappoints = this._waypoints.map((waypoint) => {
      const nearest = this.findNearestGraphPoint(
        waypoint.geometry.coordinates,
        this.coordMap,
        waypoint.properties?.floor,
      );

      return this.buildPoint(
        (nearest as [number, number]) || waypoint.geometry.coordinates,
        "SNAPPOINT",
        { floor: waypoint.properties?.floor },
      );
    });
  }

  public loadMapData(geoJson: GeoJSON.FeatureCollection) {
    const coordMap = new Map<string, Set<GeoJSON.Position[]>>();

    this.coordMap = coordMap;

    geoJson.features.forEach((feature) => {
      if (feature.geometry.type === "LineString" && feature.properties) {
        const coordinates = feature.geometry.coordinates;

        coordinates.forEach((coord) => {
          const key = JSON.stringify(coord);
          if (!coordMap.has(key)) {
            coordMap.set(key, new Set());
          }
          coordMap.get(key)?.add(coordinates);
        });
      }
    });

    geoJson.features.forEach((feature) => {
      if (feature.geometry.type === "LineString" && feature.properties) {
        const coordinates = feature.geometry.coordinates;

        for (let i = 0; i < coordinates.length - 1; i++) {
          const from = JSON.stringify(coordinates[i]);
          const to = JSON.stringify(coordinates[i + 1]);

          const toIsRoutable = feature.properties.to_is_routable;
          const fromIsRoutable = feature.properties.from_is_routable;

          const toFloor = feature.properties.to_floor;
          const fromFloor = feature.properties.from_floor;

          // Calculate distance as weight
          const weight = this.calculateDistance(
            coordinates[i],
            coordinates[i + 1],
          );

          this.graph.addEdge(
            from,
            to,
            weight,
            toIsRoutable,
            fromIsRoutable,
            toFloor,
            fromFloor,
          );

          // const fromOverlaps = coordMap.get(from);
          // if (fromOverlaps && fromOverlaps.size > 1) {
          //   fromOverlaps.forEach((otherCoords) => {
          //     if (otherCoords == coordinates) {
          //       const idx = otherCoords.findIndex(
          //         (c) => JSON.stringify(c) === from,
          //       );
          //       if (idx !== -1) {
          //         if (idx > 0) {
          //           this.graph.addEdge(
          //             from,
          //             JSON.stringify(otherCoords[idx - 1]),
          //             weight,
          //             toIsRoutable,
          //             fromIsRoutable,
          //             toFloor,
          //             fromFloor,
          //           );
          //         }
          //         if (idx < otherCoords.length - 1) {
          //           this.graph.addEdge(
          //             from,
          //             JSON.stringify(otherCoords[idx + 1]),
          //             weight,
          //             toIsRoutable,
          //             fromIsRoutable,
          //             toFloor,
          //             fromFloor,
          //           );
          //         }
          //       }
          //     }
          //   });
          // }
        }
      }
    });

    this.pathFinder.setGraph(this.graph);
  }
  /**
   * Replaces all the waypoints with the specified ones and re-fetches the routes.
   *
   * @param waypoints The coordinates at which the waypoints should be added
   */
  public setWaypoints(waypoints: POI[]) {
    // this.abortController?.abort();

    this._waypoints = waypoints.map((waypoint) =>
      buildPoint(
        waypoint.coordinates as [number, number],
        "WAYPOINT",
        waypoint.properties,
      ),
    );
    this.assignWaypointsCategories();

    const waypointEvent = new IndoorDirectionsWaypointEvent(
      "setwaypoints",
      undefined,
    );

    this.updateSnapPoints();

    this.fire(waypointEvent);

    try {
      this.calculateDirections(waypointEvent);
    } catch (error) {
      console.error(error);
    }
  }

  protected calculateDirections(originalEvent: IndoorDirectionsWaypointEvent) {
    //this.abortController?.abort();

    const routes: GeoJSON.Position[] = [];

    if (this.snappoints.length >= 2) {
      this.fire(
        new IndoorDirectionsRoutingEvent("calculateroutesstart", originalEvent),
      );

      for (let i = 0; i < this.snappoints.length - 1; i++) {
        const start = this.snappoints[i].geometry.coordinates;
        const end = this.snappoints[i + 1].geometry.coordinates;

        const segmentRoute = this.pathFinder.dijkstra(start, end);

        if (i === 0) {
          routes.push(...segmentRoute);
        } else {
          routes.push(...segmentRoute.slice(1));
        }
      }

      this.fire(
        new IndoorDirectionsRoutingEvent("calculateroutesend", originalEvent),
      );

      this.routelines = this.buildRouteLines(routes);
    } else {
      this.routelines = [];
    }
    const currentFloor = useFloorStore.getState().currentFloor;

    this.draw(currentFloor);
  }

  protected draw(currentFloor: number) {
    const features = [
      ...this._waypoints,
      ...this.snappoints,
      ...this.snaplines,
      ...this.routelines,
    ];

    const currentFeatures = features.filter(
      (feat) => feat.properties?.floor === currentFloor,
    );

    const geoJson: GeoJSON.FeatureCollection = {
      type: "FeatureCollection",
      features: currentFeatures,
    };

    if (this.map.getSource(this.configuration.sourceName)) {
      (
        this.map.getSource(
          this.configuration.sourceName,
        ) as maplibregl.GeoJSONSource
      ).setData(geoJson);
    }
  }

  protected assignWaypointsCategories() {
    this._waypoints.forEach((waypoint, index) => {
      let category;
      if (index === 0) {
        category = "ORIGIN";
      } else if (index === this._waypoints.length - 1) {
        category = "DESTINATION";
      } else {
        category = undefined;
      }

      if (waypoint.properties) {
        waypoint.properties.index = index;
        waypoint.properties.category = category;
      }
    });
  }

  /**
   * Clears the map from all the instance's traces: waypoints, snappoints, routes, etc.
   */
  clear() {
    this.setWaypoints([]);
    this.routelines = [];
  }
}
