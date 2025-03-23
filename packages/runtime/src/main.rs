use simple_logger::SimpleLogger;
use tempfile::Builder;
use std::fs::File;
use std::io::Write;
use std::cmp::min;
use futures_util::StreamExt;
use indicatif::{ProgressBar, ProgressStyle};
use anyhow::{Context, Result};
use std::path::PathBuf;

type Result<T> = std::result::Result<T, anyhow::Error>;

async fn download_firefox_source(version: &str) -> Result<PathBuf> {
    log::debug!("Downloading firefox source code for version {}", version);

    let url = format!(
        "https://archive.mozilla.org/pub/firefox/releases/{}/source/firefox-{}.source.tar.xz",
        version, version
    );

    let tmp_dir = Builder::new()
        .prefix("warpfox")
        .tempdir()
        .context("Failed to create temporary directory")?;

    let response = reqwest::get(&url)
        .await
        .context(format!("Failed to GET from '{}'", &url))?;

    let total_size = response
        .content_length()
        .ok_or_else(|| anyhow::anyhow!("Failed to get content length from '{}'", &url))?;

    let pb = ProgressBar::new(total_size);
    pb.set_style(
        ProgressStyle::default_bar()
            .template("{msg}\n{spinner:.green} [{elapsed_precise}] [{wide_bar:.cyan/blue}] {bytes}/{total_bytes} ({bytes_per_sec}, {eta})")
            .unwrap()
            .progress_chars("#>-")
    );
    pb.set_message(format!("Downloading {}", url));

    let mut downloaded: u64 = 0;
    let mut stream = response.bytes_stream();

    let fname = url.rsplit('/').next().context(format!("Failed to get filename from '{}'", &url))?;
    let fname = tmp_dir.path().join(fname);
    let mut dest = File::create(&fname).context("Failed to create file")?;

    while let Some(item) = stream.next().await {
        let chunk = item.context("Error while downloading file")?;
        dest.write_all(&chunk).context("Error while writing to file")?;
        let new = min(downloaded + (chunk.len() as u64), total_size);
        downloaded = new;
        pb.set_position(new);
    }

    pb.finish();
    Ok(tmp_dir.into_path())
}

fn unpack_firefox_source(source_tar: PathBuf) -> Result<PathBuf> {
    log::debug!("Unpacking firefox source code");

    let output = PathBuf::from("engine");
    std::fs::create_dir_all(&output).context("Failed to create 'engine' directory")?;

    let status = std::process::Command::new("tar")
        .arg("-xf")
        .arg(&source_tar)
        .arg("--strip-components=1")
        .arg("-C")
        .arg(&output)
        .status()
        .context("Failed to execute tar command")?;

    if !status.success() {
        return Err(anyhow::anyhow!("tar command failed with status: {}", status));
    }

    Ok(output)
}

fn cleanup(source_tar_dir: &PathBuf) -> Result<()> {
    log::info!("Cleaning up");
    std::fs::remove_dir_all(source_tar_dir).context("Failed to remove temporary directory")?;
    Ok(())
}

#[tokio::main]
async fn main() -> Result<()> {
    SimpleLogger::new()
        .with_colors(true)
        .without_timestamps()
        .init()
        .context("Failed to initialize logger")?;

    let manifest: serde_json::Value = serde_json::from_str(include_str!("../../../firefox.json"))
        .context("Failed to parse firefox.json")?;
    let version = manifest["version"]
        .as_str()
        .context("Missing 'version' in firefox.json")?;

    log::info!("Starting runtime for firefox v{}", version);
    let source_tar_dir = download_firefox_source(version).await?;
    let source_tar = source_tar_dir.join(format!("firefox-{}.source.tar.xz", version));
    log::info!("Downloaded source code to {:?}", source_tar);
    let source_dir = unpack_firefox_source(source_tar)?;
    log::info!("Unpacked source code to {:?}", source_dir);

    cleanup(&source_tar_dir)?;
    Ok(())
}