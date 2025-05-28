import { Vertex, Edge } from "../types";

export default class Graph {
  adjacencyList: Map<Vertex, Edge[]> = new Map();
  propertiesMap: Map<Vertex, { isRoutable: boolean; floor: number }> =
    new Map();

  addVertex(Vertex: Vertex, isRoutable: boolean, floor: number) {
    const base = Vertex.split("]")[0];
    const key = `${base},${floor}]`;
    if (!this.adjacencyList.has(key)) {
      this.adjacencyList.set(key, []);
      this.propertiesMap.set(key, { isRoutable, floor });
    }
  }

  addEdge(
    from: Vertex,
    to: Vertex,
    weight: number,
    toIsRoutable: boolean,
    fromIsRoutable: boolean,
    toFloor: number,
    fromFloor: number,
  ) {
    const fromBase = from.split("]")[0];
    const toBase = to.split("]")[0];
    const fromKey = `${fromBase},${fromFloor}]`;
    const toKey = `${toBase},${toFloor}]`;

    this.addVertex(from, fromIsRoutable, toFloor);
    this.addVertex(to, toIsRoutable, fromFloor);

    this.adjacencyList.get(fromKey)?.push({ to: toKey, weight });
    this.adjacencyList.get(toKey)?.push({ to: fromKey, weight });
  }

  getVertices() {
    return [...this.adjacencyList.keys()];
  }

  public getVertexProperties?(
    vertex: string,
  ): { isRoutable: boolean; floor: number } | undefined {
    return this.propertiesMap.get(vertex);
  }

  getEdges(Vertex: Vertex): Edge[] {
    return this.adjacencyList.get(Vertex) || [];
  }

  hasVertex(Vertex: Vertex) {
    return this.adjacencyList.has(Vertex);
  }
}
