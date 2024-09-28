.libPaths("~/R/library")
options(repos = c(CRAN = "https://cran.rstudio.com"))

#if (!require(nflreadr)) {
 # install.packages("nflreadr", repos = c("https://nflverse.r-universe.dev", getOption("repos")))

  install.packages("nflreadr")
#}

library(nflreadr)

output_dir <- "pbp_data"
if (!dir.exists(output_dir)) {
  dir.create(output_dir)
}

start_year <- 1999
end_year <- as.numeric(format(Sys.Date(), "%Y")) # Current year

for (year in start_year:end_year) {
  cat("Downloading play-by-play data for the", year, "season...\n")
  
  pbp_data <- load_pbp(year)
  
  file_path <- paste0(output_dir, "/play_by_play_", year, ".csv")
  
  write.csv(pbp_data, file_path, row.names = FALSE)
  
  cat("Saved play-by-play data for the", year, "season to", file_path, "\n")
}

cat("All seasons from", start_year, "to", end_year, "have been downloaded and saved.\n")
