export type TreemapInput<T> = { value: number, item: T };

export type TreemapRect<T> = { x: number, y: number, width: number, height: number, item: T };

type Box = { x: number, y: number, width: number, height: number };

function worst(row: number[], side: number): number {
    const sum = row.reduce((a, b) => a + b, 0);
    const max = Math.max(...row);
    const min = Math.min(...row);
    return Math.max((side * side * max) / (sum * sum), (sum * sum) / (side * side * min));
}

function layoutRow<T>(row: TreemapInput<T>[], areas: number[], box: Box, out: TreemapRect<T>[]): Box {
    const sum = areas.reduce((a, b) => a + b, 0);
    if (box.width >= box.height) {
        const width = sum / box.height;
        let y = box.y;
        row.forEach((entry, i) => {
            const height = areas[i] / width;
            out.push({ x: box.x, y, width, height, item: entry.item });
            y += height;
        });
        return { x: box.x + width, y: box.y, width: box.width - width, height: box.height };
    }

    const height = sum / box.width;
    let x = box.x;
    row.forEach((entry, i) => {
        const width = areas[i] / height;
        out.push({ x, y: box.y, width, height, item: entry.item });
        x += width;
    });
    return { x: box.x, y: box.y + height, width: box.width, height: box.height - height };
}

export function squarify<T>(inputs: TreemapInput<T>[], width: number, height: number): TreemapRect<T>[] {
    const entries = inputs.filter(i => i.value > 0).sort((a, b) => b.value - a.value);
    const total = entries.reduce((sum, e) => sum + e.value, 0);
    if (total === 0 || width <= 0 || height <= 0) return [];

    const scale = (width * height) / total;
    const out: TreemapRect<T>[] = [];
    let box: Box = { x: 0, y: 0, width, height };
    let row: TreemapInput<T>[] = [];
    let areas: number[] = [];

    for (const entry of entries) {
        const area = entry.value * scale;
        const side = Math.min(box.width, box.height);
        if (row.length === 0 || worst([...areas, area], side) <= worst(areas, side)) {
            row.push(entry);
            areas.push(area);
            continue;
        }
        box = layoutRow(row, areas, box, out);
        row = [entry];
        areas = [area];
    }
    if (row.length) layoutRow(row, areas, box, out);

    return out;
}
