import { nanoid } from "nanoid";
import {
  MapLibreGlDirectionsConfiguration,
  MapLibreGlIndoorDirectionsDefaultConfiguration,
  PointType,
} from "../types";
import layersFactory from "./layers";

export function buildConfiguration(
  customConfiguration?: Partial<MapLibreGlDirectionsConfiguration>,
): MapLibreGlDirectionsConfiguration {
  const layers = layersFactory(
    customConfiguration?.pointsScalingFactor,
    customConfiguration?.linesScalingFactor,
    customConfiguration?.sourceName,
  );

  return Object.assign(
    {},
    MapLibreGlIndoorDirectionsDefaultConfiguration,
    { layers },
    customConfiguration,
  );
}

/**
 * @protected
 *
 * Creates a {@link Feature<Point>|GeoJSON Point Feature} of one of the ${@link PointType|known types} with a given
 * coordinate.
 */
export function buildPoint(
  coordinate: [number, number],
  type: PointType,
  properties?: Record<string, unknown>,
): GeoJSON.Feature<GeoJSON.Point> {
  return {
    type: "Feature",
    geometry: {
      type: "Point",
      coordinates: coordinate,
    },
    properties: {
      type,
      id: nanoid(),
      ...properties,
    },
  };
}

export function buildRouteLines(
  coordinates: GeoJSON.Position[],
  routeIndex = 0,
  legIndex = 0,
  origin?: GeoJSON.Feature,
  destination?: GeoJSON.Feature,
): GeoJSON.LineString[] {
  const generalProperties = {
    id: nanoid(),
    route: "SELECTED",
    routeIndex,
    legIndex,
    congestion: 0,
    departSnappointProperties: {
      type: "SNAPPOINT",
      id: nanoid(),
      profile: "walking",
      waypointProperties: {
        type: "WAYPOINT",
        id: origin?.properties?.id || nanoid(),
        profile: "walking",
        index: 0,
        category: "ORIGIN",
      },
    },
    arriveSnappointProperties: {
      type: "SNAPPOINT",
      id: nanoid(),
      profile: "walking",
      waypointProperties: {
        type: "WAYPOINT",
        id: destination?.properties?.id || nanoid(),
        profile: "walking",
        index: 1,
        category: "DESTINATION",
      },
    },
  };
  const features: { [id: number]: GeoJSON.Feature } = {};
  const floorsUsed = new Set();
  for (let i = 0; i < coordinates.length - 1; i++) {
    const coordsTriple = coordinates[i];
    const floor = coordsTriple[2];
    if (!floorsUsed.has(floor)) {
      floorsUsed.add(floor);
      const feature = {
        type: "Feature",
        id: floor,
        properties: {
          ...generalProperties,
          floor,
        },
        geometry: {
          type: "LineString",
          coordinates: [[coordsTriple[0], coordsTriple[1]]],
        },
      } as GeoJSON.Feature;
      features[floor] = feature;
    }
    {
      features[floor].geometry.coordinates.push([
        coordsTriple[0],
        coordsTriple[1],
      ]);
    }
  }
  return Object.values(features);
}

export function buildSnaplines(
  waypoints: GeoJSON.Feature<GeoJSON.Point>[],
  snappoints: GeoJSON.Feature<GeoJSON.Point>[],
): GeoJSON.Feature<GeoJSON.LineString>[] {
  const snaplines = waypoints.map((waypoint, index) => {
    return {
      type: "Feature",
      geometry: {
        type: "LineString",
        coordinates: [
          [waypoint.geometry.coordinates[0], waypoint.geometry.coordinates[1]],
          [
            snappoints[index].geometry.coordinates[0],
            snappoints[index].geometry.coordinates[1],
          ],
        ],
      },
      properties: {
        type: "SNAPLINE",
        floor: waypoint.properties?.floor,
      },
    } as GeoJSON.Feature<GeoJSON.LineString>;
  });
  return snaplines;
}
