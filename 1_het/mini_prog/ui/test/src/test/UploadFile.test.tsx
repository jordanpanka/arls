import { render, screen, fireEvent } from "@testing-library/preact";
import { describe, it, expect, vi } from "vitest";
import { UploadFile } from "../components/upload/uploadFile";

vi.mock("@mui/material", () => ({
  Dialog: (p: any) => (p.open ? <div>{p.children}</div> : null),
  DialogTitle: (p: any) => <h2>{p.children}</h2>,
  DialogContent: (p: any) => <div>{p.children}</div>,
  DialogActions: (p: any) => <div>{p.children}</div>,
  Box: (p: any) => <div>{p.children}</div>,
}));

const emptyRepo = { owner: "", name: "", reference: "" };

function renderDialog(props: any = {}) {
  return render(
    <UploadFile
      open={true}
      setOpen={vi.fn()}
      setFile={vi.fn()}
      link={vi.fn()}
      repo={emptyRepo}
      setRepo={vi.fn()}
      importRepo={vi.fn()}
      busy={false}
      result=""
      {...props}
    />
  );
}

describe("UploadFile", () => {
  it("megjeleníti a fájlválasztókat", () => {
    renderDialog();

    expect(screen.getByText("Choose files")).toBeInTheDocument();
    expect(screen.getByText("Choose a directory")).toBeInTheDocument();
    expect(screen.getByText("Upload")).toBeInTheDocument();
  });

  it("Cancel gombra bezár", () => {
    const setOpen = vi.fn();

    renderDialog({ setOpen });

    fireEvent.click(screen.getByText("Cancel"));

    expect(setOpen).toHaveBeenCalledWith(false);
  });

  it("Upload gombra meghívja a link függvényt", () => {
    const link = vi.fn();

    renderDialog({ link });

    fireEvent.click(screen.getByText("Upload"));

    expect(link).toHaveBeenCalled();
  });

  it("GitHub repository fülre váltva a repo mezőket mutatja", () => {
    renderDialog();

    fireEvent.click(screen.getByText("GitHub repository"));

    expect(screen.getByText("Owner")).toBeInTheDocument();
    expect(screen.getByText("Repository")).toBeInTheDocument();
    expect(screen.getByText("Branch, tag or commit")).toBeInTheDocument();
    expect(screen.queryByText("Choose files")).not.toBeInTheDocument();
    expect(screen.queryByText("Upload")).not.toBeInTheDocument();
  });

  it("Import gombra meghívja az importRepo függvényt", () => {
    const importRepo = vi.fn();

    renderDialog({ importRepo, repo: { owner: "octocat", name: "Hello-World", reference: "" } });

    fireEvent.click(screen.getByText("GitHub repository"));
    fireEvent.click(screen.getByText("Import"));

    expect(importRepo).toHaveBeenCalled();
  });

  it("owner mező gépelésekor frissíti a repo state-et", () => {
    const setRepo = vi.fn();

    renderDialog({ setRepo });

    fireEvent.click(screen.getByText("GitHub repository"));
    fireEvent.input(screen.getByPlaceholderText("octocat"), { target: { value: "preactjs" } });

    expect(setRepo).toHaveBeenCalledWith({ owner: "preactjs", name: "", reference: "" });
  });

  it("importálás közben letiltja a gombokat és jelzi a folyamatot", () => {
    renderDialog({ busy: true });

    expect(screen.getByText("Import in progress…")).toBeInTheDocument();
    expect(screen.getByText("Cancel")).toBeDisabled();
    expect(screen.getByText("Upload")).toBeDisabled();
  });

  it("megjeleníti az eredményt", () => {
    renderDialog({ result: "Done: 12 files indexed, 3 skipped (abc1234)." });

    expect(screen.getByText("Done: 12 files indexed, 3 skipped (abc1234).")).toBeInTheDocument();
  });
});
