using System;
using Microsoft.EntityFrameworkCore.Migrations;

#nullable disable

namespace RagApi.Migrations
{
    /// <inheritdoc />
    public partial class AddCodeMetrics : Migration
    {
        /// <inheritdoc />
        protected override void Up(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.CreateTable(
                name: "MetricsAnalysis",
                columns: table => new
                {
                    ID = table.Column<int>(type: "int", nullable: false)
                        .Annotation("SqlServer:Identity", "1, 1"),
                    ProjectID = table.Column<int>(type: "int", nullable: false),
                    RepositoryID = table.Column<int>(type: "int", nullable: true),
                    Status = table.Column<string>(type: "nvarchar(450)", nullable: false),
                    StaticStatus = table.Column<string>(type: "nvarchar(max)", nullable: false),
                    GraphStatus = table.Column<string>(type: "nvarchar(max)", nullable: false),
                    ErrorMessage = table.Column<string>(type: "nvarchar(max)", nullable: true),
                    Trigger = table.Column<string>(type: "nvarchar(max)", nullable: false),
                    Branch = table.Column<string>(type: "nvarchar(max)", nullable: true),
                    CommitSha = table.Column<string>(type: "nvarchar(max)", nullable: true),
                    FileSetHash = table.Column<string>(type: "nvarchar(max)", nullable: true),
                    StaticAnalyzer = table.Column<string>(type: "nvarchar(max)", nullable: false),
                    GraphAnalyzer = table.Column<string>(type: "nvarchar(max)", nullable: true),
                    CreatedAt = table.Column<DateTime>(type: "datetime2", nullable: false),
                    StartedAt = table.Column<DateTime>(type: "datetime2", nullable: true),
                    CompletedAt = table.Column<DateTime>(type: "datetime2", nullable: true),
                    TotalDurationMs = table.Column<double>(type: "float", nullable: true),
                    StaticDurationMs = table.Column<double>(type: "float", nullable: true),
                    GraphDurationMs = table.Column<double>(type: "float", nullable: true),
                    FilesAnalyzed = table.Column<int>(type: "int", nullable: false),
                    FilesSkipped = table.Column<int>(type: "int", nullable: false),
                    SkippedFilesJson = table.Column<string>(type: "nvarchar(max)", nullable: true),
                    TotalNloc = table.Column<int>(type: "int", nullable: false),
                    TotalFunctions = table.Column<int>(type: "int", nullable: false),
                    TotalClasses = table.Column<int>(type: "int", nullable: true),
                    AverageComplexity = table.Column<double>(type: "float", nullable: true),
                    MaxComplexity = table.Column<int>(type: "int", nullable: true),
                    HighComplexityFunctionCount = table.Column<int>(type: "int", nullable: false),
                    LongFunctionCount = table.Column<int>(type: "int", nullable: false),
                    ManyParameterFunctionCount = table.Column<int>(type: "int", nullable: false),
                    DependencyCount = table.Column<int>(type: "int", nullable: true),
                    CycleCount = table.Column<int>(type: "int", nullable: true),
                    AverageFanIn = table.Column<double>(type: "float", nullable: true),
                    AverageFanOut = table.Column<double>(type: "float", nullable: true),
                    MaxFanIn = table.Column<int>(type: "int", nullable: true),
                    MaxFanOut = table.Column<int>(type: "int", nullable: true),
                    MaxDependencyDepth = table.Column<int>(type: "int", nullable: true),
                    CyclesJson = table.Column<string>(type: "nvarchar(max)", nullable: true),
                    ThresholdsJson = table.Column<string>(type: "nvarchar(max)", nullable: false)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_MetricsAnalysis", x => x.ID);
                    table.ForeignKey(
                        name: "FK_MetricsAnalysis_Project_ProjectID",
                        column: x => x.ProjectID,
                        principalTable: "Project",
                        principalColumn: "ID",
                        onDelete: ReferentialAction.Cascade);
                });

            migrationBuilder.CreateTable(
                name: "FileMetric",
                columns: table => new
                {
                    ID = table.Column<int>(type: "int", nullable: false)
                        .Annotation("SqlServer:Identity", "1, 1"),
                    AnalysisID = table.Column<int>(type: "int", nullable: false),
                    FileID = table.Column<int>(type: "int", nullable: true),
                    Path = table.Column<string>(type: "nvarchar(450)", maxLength: 450, nullable: false),
                    Language = table.Column<string>(type: "nvarchar(max)", nullable: false),
                    Nloc = table.Column<int>(type: "int", nullable: false),
                    TokenCount = table.Column<int>(type: "int", nullable: false),
                    FunctionCount = table.Column<int>(type: "int", nullable: false),
                    ClassCount = table.Column<int>(type: "int", nullable: true),
                    AverageComplexity = table.Column<double>(type: "float", nullable: true),
                    MaxComplexity = table.Column<int>(type: "int", nullable: true),
                    HighComplexityFunctionCount = table.Column<int>(type: "int", nullable: false),
                    AverageFunctionNloc = table.Column<double>(type: "float", nullable: true),
                    MaxFunctionNloc = table.Column<int>(type: "int", nullable: true),
                    LongFunctionCount = table.Column<int>(type: "int", nullable: false),
                    ManyParameterFunctionCount = table.Column<int>(type: "int", nullable: false),
                    FanIn = table.Column<int>(type: "int", nullable: true),
                    FanOut = table.Column<int>(type: "int", nullable: true),
                    ImportCount = table.Column<int>(type: "int", nullable: true)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_FileMetric", x => x.ID);
                    table.ForeignKey(
                        name: "FK_FileMetric_MetricsAnalysis_AnalysisID",
                        column: x => x.AnalysisID,
                        principalTable: "MetricsAnalysis",
                        principalColumn: "ID",
                        onDelete: ReferentialAction.Cascade);
                });

            migrationBuilder.CreateTable(
                name: "FunctionMetric",
                columns: table => new
                {
                    ID = table.Column<int>(type: "int", nullable: false)
                        .Annotation("SqlServer:Identity", "1, 1"),
                    FileMetricID = table.Column<int>(type: "int", nullable: false),
                    Name = table.Column<string>(type: "nvarchar(max)", nullable: false),
                    LongName = table.Column<string>(type: "nvarchar(max)", nullable: false),
                    ClassName = table.Column<string>(type: "nvarchar(max)", nullable: true),
                    StartLine = table.Column<int>(type: "int", nullable: false),
                    EndLine = table.Column<int>(type: "int", nullable: false),
                    Nloc = table.Column<int>(type: "int", nullable: false),
                    CyclomaticComplexity = table.Column<int>(type: "int", nullable: false),
                    TokenCount = table.Column<int>(type: "int", nullable: false),
                    ParameterCount = table.Column<int>(type: "int", nullable: false),
                    Length = table.Column<int>(type: "int", nullable: false),
                    FanIn = table.Column<int>(type: "int", nullable: true),
                    FanOut = table.Column<int>(type: "int", nullable: true)
                },
                constraints: table =>
                {
                    table.PrimaryKey("PK_FunctionMetric", x => x.ID);
                    table.ForeignKey(
                        name: "FK_FunctionMetric_FileMetric_FileMetricID",
                        column: x => x.FileMetricID,
                        principalTable: "FileMetric",
                        principalColumn: "ID",
                        onDelete: ReferentialAction.Cascade);
                });

            migrationBuilder.CreateIndex(
                name: "IX_FileMetric_AnalysisID_Path",
                table: "FileMetric",
                columns: new[] { "AnalysisID", "Path" });

            migrationBuilder.CreateIndex(
                name: "IX_FunctionMetric_FileMetricID",
                table: "FunctionMetric",
                column: "FileMetricID");

            migrationBuilder.CreateIndex(
                name: "IX_MetricsAnalysis_ProjectID_Status",
                table: "MetricsAnalysis",
                columns: new[] { "ProjectID", "Status" });
        }

        /// <inheritdoc />
        protected override void Down(MigrationBuilder migrationBuilder)
        {
            migrationBuilder.DropTable(
                name: "FunctionMetric");

            migrationBuilder.DropTable(
                name: "FileMetric");

            migrationBuilder.DropTable(
                name: "MetricsAnalysis");
        }
    }
}
