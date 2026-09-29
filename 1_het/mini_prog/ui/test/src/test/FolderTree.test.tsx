import { render, screen, fireEvent } from "@testing-library/preact";
import { describe, it, expect, vi } from "vitest";
import { buildTree, FolderTree } from "../components/layout/FolderTree";

vi.mock("@mui/material", () => ({
  ListItemText: (props: any) => <span>{props.primary}</span>,
  ListItemButton: (props: any) => <button {...props}>{props.children}</button>,
  Collapse: (props: any) => props.in ? <div>{props.children}</div> : null,
  List: (props: any) => <div>{props.children}</div>,
}));

vi.mock("@mui/icons-material", () => ({
  ExpandLess: () => <span>less</span>,
  ExpandMore: () => <span>more</span>,
}));

describe("FolderTree", () => {
  it("felépíti a fájlstruktúrát", () => {
    const tree = buildTree([
      { id: 1, name: "a.ts", relativePath: "src/a.ts" },
      { id: 2, name: "b.ts", relativePath: "src/components/b.ts" },
    ]);

    expect(tree.folders[0].name).toBe("src");
    expect(tree.folders[0].files[0].name).toBe("a.ts");
    expect(tree.folders[0].folders[0].name).toBe("components");
  });

  it("megjeleníti a fájlokat és kattintásra meghívja az onFileClick-et", () => {
    const onFileClick = vi.fn();

    const tree = buildTree([
      { id: 1, name: "Chat.tsx", relativePath: "src/Chat.tsx" },
    ]);

    render(<FolderTree node={tree} level={0} onFileClick={onFileClick} />);

    const file = screen.getByText("Chat.tsx");
    fireEvent.click(file);

    expect(onFileClick).toHaveBeenCalledWith({
      id: 1,
      name: "Chat.tsx",
      relativePath: "src/Chat.tsx",
    });
  });
});