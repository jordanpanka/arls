import { render, screen, fireEvent, waitFor } from "@testing-library/preact";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { Login } from "../pages/login";

const routeMock = vi.fn();

vi.mock("preact-iso", () => ({
  useLocation: () => ({
    route: routeMock,
  }),
}));

vi.mock("../assets/avatar.png", () => ({
  default: "avatar.png",
}));

describe("Login", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
  });

  it("megjeleníti a login mezőket", () => {
    render(<Login />);

    expect(screen.getByPlaceholderText("Email address")).toBeInTheDocument();
    expect(screen.getByPlaceholderText("Password")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Login" })).toBeInTheDocument();
  });

  it("be lehet írni emailt és jelszót", () => {
    render(<Login />);

    const email = screen.getByPlaceholderText("Email address");
    const password = screen.getByPlaceholderText("Password");

    fireEvent.input(email, { target: { value: "teszt@test.hu" } });
    fireEvent.input(password, { target: { value: "123456" } });

    expect(email).toHaveValue("teszt@test.hu");
    expect(password).toHaveValue("123456");
  });

  it("sikeres login után elmenti a tokent és átirányít", async () => {
    vi.stubGlobal("fetch", vi.fn(() =>
      Promise.resolve({
        ok: true,
        json: () => Promise.resolve({
          token: "test-token",
          firstName: "Teszt",
          lastName: "Elek",
        }),
      })
    ));

    render(<Login />);

    fireEvent.input(screen.getByPlaceholderText("Email address"), {
      target: { value: "teszt@test.hu" },
    });

    fireEvent.input(screen.getByPlaceholderText("Password"), {
      target: { value: "123456" },
    });

    fireEvent.click(screen.getByRole("button", { name: "Login" }));

    await waitFor(() => {
      expect(localStorage.getItem("token")).toBe("test-token");
      expect(routeMock).toHaveBeenCalledWith("/chat", true);
    });
  });

  it("register linkre megjelennek a regisztrációs mezők", () => {
    render(<Login />);

    fireEvent.click(screen.getByText("Register"));

    expect(screen.getByPlaceholderText("First name")).toBeInTheDocument();
    expect(screen.getByPlaceholderText("Last name")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Register" })).toBeInTheDocument();
  });
});