import { Vertex, Edge } from "../types";

export default class Graph {
  adjacencyList: Map<Vertex, Edge[]> = new Map();
  propertiesMap: Map<Vertex, { isRoutable: boolean }> = new Map();

  addVertex(Vertex: Vertex, isRoutable: boolean) {
    if (!this.adjacencyList.has(Vertex)) {
      this.adjacencyList.set(Vertex, []);
      this.propertiesMap.set(Vertex, { isRoutable });
    }
  }

  addEdge(
    from: Vertex,
    to: Vertex,
    weight: number,
    toIsRoutable: boolean,
    fromIsRoutable: boolean,
  ) {
    this.addVertex(from, fromIsRoutable);
    this.addVertex(to, toIsRoutable);
    this.adjacencyList.get(from)?.push({ to, weight });
    this.adjacencyList.get(to)?.push({ to: from, weight });
  }

  getVertices() {
    return [...this.adjacencyList.keys()];
  }

  public getVertexProperties?(
    vertex: string,
  ): { isRoutable: boolean } | undefined {
    return this.propertiesMap.get(vertex);
  }

  getEdges(Vertex: Vertex): Edge[] {
    return this.adjacencyList.get(Vertex) || [];
  }

  hasVertex(Vertex: Vertex) {
    return this.adjacencyList.has(Vertex);
  }
}
