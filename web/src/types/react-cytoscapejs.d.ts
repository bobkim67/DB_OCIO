// Minimal module declaration for react-cytoscapejs (no upstream types).
declare module "react-cytoscapejs" {
  import type { CSSProperties } from "react";
  import type { Core, ElementDefinition, LayoutOptions, Stylesheet } from "cytoscape";

  export interface CytoscapeComponentProps {
    elements: ElementDefinition[];
    style?: CSSProperties;
    stylesheet?: Stylesheet[] | unknown[];
    layout?: LayoutOptions | Record<string, unknown>;
    cy?: (cy: Core) => void;
    minZoom?: number;
    maxZoom?: number;
    autoungrabify?: boolean;
    autounselectify?: boolean;
    boxSelectionEnabled?: boolean;
    pan?: { x: number; y: number };
    zoom?: number;
    wheelSensitivity?: number;
    className?: string;
    id?: string;
  }

  const CytoscapeComponent: React.FC<CytoscapeComponentProps> & {
    normalizeElements: (elements: { nodes?: unknown[]; edges?: unknown[] } | unknown[]) => unknown[];
  };

  export default CytoscapeComponent;
}
